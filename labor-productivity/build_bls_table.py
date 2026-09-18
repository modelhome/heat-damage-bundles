#!/usr/bin/env python3
"""Build `bls_labor.csv`: heat-exposed outdoor workers and their mean wage, per city.

Run once, by hand, when the table needs rebuilding. It is **not** in the Docker
image and the model never calls it: the runner reads only the committed CSV.

    python build_bls_table.py [path/to/cities.json] [-o bls_labor.csv]

`cities.json` is `thermal-indices`' committed city list, so the table is keyed to
exactly the cities the upstream model emits. Each city's coordinates are resolved
to a metropolitan statistical area through the Census geocoder, and that MSA's
employment and wages come from the BLS OEWS release through the BLS public API.

Two sources, both public and keyless:

- Census geocoder (geocoding.geo.census.gov), "Metropolitan Statistical Areas"
  layer, current vintage. A point with no MSA falls back to its state.
- BLS public data API (api.bls.gov), OEWS series. BLS blocks automated retrieval
  of the OEWS flat files at their edge, so the API is the only programmatic route
  to the same numbers. Keyless, it is v1: 25 series per query and **25 queries
  per day**, which this table needs 22 of. Set `BLS_API_KEY` to a free
  registration key (https://data.bls.gov/registrationEngine/) and it uses v2
  instead: 50 series per query, 500 queries per day.

Every successful response is cached under .bls-cache/, so a rerun costs nothing
and an interrupted build resumes where it stopped rather than starting over.

The heat-exposed set is a modelling choice, documented in the bundle README:

    47-0000  Construction and extraction occupations
    45-0000  Farming, fishing and forestry occupations
    37-3011  Landscaping and groundskeeping workers
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / ".bls-cache"
DEFAULT_CITIES = Path.home() / "repos" / "thermofeel-bundles" / "thermal-indices" / "cities.json"
DEFAULT_OUTPUT = HERE / "bls_labor.csv"

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
BLS_API_V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_API_V2_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_REGISTRATION_URL = "https://data.bls.gov/registrationEngine/"

OEWS_YEAR = "2025"
OEWS_RELEASE = "May 2025"
SOURCE = "BLS Occupational Employment and Wage Statistics (OEWS), via the BLS public data API"

# SOC groups counted as heat-exposed outdoor labour.
SOC_CODES = ("470000", "450000", "373011")
SOC_LABEL = "47-0000;45-0000;37-3011"

DATATYPE_EMPLOYMENT = "01"
DATATYPE_HOURLY_MEAN_WAGE = "03"

# BLS limits: 25 series per query keyless (v1), 50 with a key (v2). Stay under.
SERIES_PER_QUERY_KEYLESS = 24
SERIES_PER_QUERY_KEYED = 48

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}


def log(message: str) -> None:
    print(message, file=sys.stderr)


def numeric(value: str | None) -> bool:
    """True when an OEWS value is a number rather than a suppression marker."""
    if value is None:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


def cached(name: str, produce) -> dict:
    """Return the cached JSON for *name*, calling *produce* once if it is absent."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    payload = produce()
    path.write_text(json.dumps(payload))
    return payload


def series_id(area_type: str, area_code: str, soc: str, datatype: str) -> str:
    """An OEWS series id: OEU + area type + 7-digit area + industry + SOC + datatype."""
    identifier = f"OEU{area_type}{area_code:0>7}000000{soc}{datatype}"
    if len(identifier) != 25:
        raise ValueError(f"malformed series id {identifier!r}")
    return identifier


def lookup_area(city: dict) -> tuple[str, str, str, str]:
    """(area_type, area_code, area_title, match_method) for one city."""
    key = f"geo_{city['name'].lower().replace(' ', '-')}_{city['state'].lower()}"

    def fetch() -> dict:
        query = urllib.parse.urlencode(
            {
                "x": city["lon"],
                "y": city["lat"],
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "layers": "Metropolitan Statistical Areas",
                "format": "json",
            }
        )
        with urllib.request.urlopen(f"{GEOCODER_URL}?{query}", timeout=60) as response:
            return json.loads(response.read())

    payload = cached(key, fetch)
    areas = payload.get("result", {}).get("geographies", {}).get("Metropolitan Statistical Areas", [])
    if areas:
        area = areas[0]
        return "M", area["GEOID"], area["NAME"], "msa"

    # No MSA covers this point (a micropolitan or rural capital such as Pierre or
    # Montpelier). Fall back to the state, not to the nearest metro: the nearest
    # cached metro can be several hundred miles and a different labour market
    # entirely, which would produce a plausible-looking wrong number.
    # OEWS state area codes are the 2-digit state FIPS followed by five zeros.
    fips = STATE_FIPS[city["state"]]
    return "S", f"{fips}00000", f"{city['state']} (statewide)", "state fallback: no MSA covers this point"


class QuotaExhausted(RuntimeError):
    """The BLS API turned the query away because the daily allowance is spent."""


def fetch_series(ids: list[str]) -> tuple[dict[str, str | None], int]:
    """Fetch OEWS values for *ids* in batches.

    Returns ({series_id: value or None}, unfetched_series_count). A spent daily
    allowance stops further queries rather than failing the whole build: every
    batch already fetched stays cached, so a later run needs only what is left.
    """
    api_key = os.environ.get("BLS_API_KEY", "").strip()
    per_query = SERIES_PER_QUERY_KEYED if api_key else SERIES_PER_QUERY_KEYLESS
    url = BLS_API_V2_URL if api_key else BLS_API_V1_URL

    values: dict[str, str | None] = {}
    unfetched = 0
    exhausted = False

    for start in range(0, len(ids), per_query):
        batch = ids[start : start + per_query]
        key = f"bls_{OEWS_YEAR}_{batch[0]}_{len(batch)}"
        cache_path = CACHE_DIR / f"{key}.json"

        if exhausted and not cache_path.exists():
            unfetched += len(batch)
            continue

        def fetch() -> dict:
            query = {"seriesid": batch, "startyear": OEWS_YEAR, "endyear": OEWS_YEAR}
            if api_key:
                query["registrationkey"] = api_key
            request = urllib.request.Request(
                url, data=json.dumps(query).encode(), headers={"Content-Type": "application/json"}
            )
            log(f"  BLS query for {len(batch)} series starting {batch[0]}")
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read())
            status = payload.get("status")
            if status != "REQUEST_SUCCEEDED":
                message = " ".join(payload.get("message") or [])
                if "threshold" in message.lower():
                    raise QuotaExhausted(message)
                raise RuntimeError(f"BLS API refused the query: {status}: {message}")
            time.sleep(1)
            return payload

        try:
            payload = cached(key, fetch)
        except QuotaExhausted as exc:
            log(f"  warning: BLS daily allowance is spent ({exc})")
            log(f"  warning: every batch fetched so far is cached in {CACHE_DIR.name}/;")
            log("  warning: rerun tomorrow, or set BLS_API_KEY from "
                f"{BLS_REGISTRATION_URL} to raise the allowance, and only the")
            log("  warning: remaining series will be fetched.")
            exhausted = True
            unfetched += len(batch)
            continue

        for series in payload["Results"]["series"]:
            data = series.get("data") or []
            values[series["seriesID"]] = data[0]["value"] if data else None

    return values, unfetched


def build(cities_path: Path, output_path: Path) -> int:
    cities = json.loads(cities_path.read_text())
    log(f"{len(cities)} cities from {cities_path}")

    areas: dict[str, tuple[str, str, str, str]] = {}
    for city in cities:
        areas[f"{city['name']}|{city['state']}"] = lookup_area(city)
    distinct = {(area_type, code) for area_type, code, _, _ in areas.values()}
    log(f"{len(distinct)} distinct OEWS areas")

    ids: list[str] = []
    for area_type, area_code in sorted(distinct):
        for soc in SOC_CODES:
            ids.append(series_id(area_type, area_code, soc, DATATYPE_EMPLOYMENT))
            ids.append(series_id(area_type, area_code, soc, DATATYPE_HOURLY_MEAN_WAGE))
    log(f"{len(ids)} OEWS series to fetch")
    values, unfetched = fetch_series(ids)

    rows = []
    for city in cities:
        area_type, area_code, area_title, method = areas[f"{city['name']}|{city['state']}"]
        workers = 0
        wage_weighted = 0.0
        suppressed = []
        for soc in SOC_CODES:
            employment = values.get(series_id(area_type, area_code, soc, DATATYPE_EMPLOYMENT))
            hourly = values.get(series_id(area_type, area_code, soc, DATATYPE_HOURLY_MEAN_WAGE))
            # OEWS suppresses small or unreliable cells, as a missing series or as
            # a non-numeric marker ("-", "*", "**", "#"). A suppressed group
            # contributes no workers and is left out of the wage mean; the count
            # travels with the row so the under-count stays visible.
            if not numeric(employment) or not numeric(hourly):
                suppressed.append(soc)
                continue
            count = int(round(float(employment)))
            workers += count
            wage_weighted += count * float(hourly)

        if workers == 0:
            log(f"  warning: no OEWS data at all for {city['name']}, {city['state']} ({area_title})")
            continue

        notes = method
        if suppressed:
            notes += f"; {len(suppressed)} of {len(SOC_CODES)} groups suppressed"
        rows.append(
            {
                "city": city["name"],
                "state": city["state"],
                "msa": area_title,
                "exposed_workers": workers,
                "mean_hourly_wage_usd": round(wage_weighted / workers, 2),
                "soc_codes": SOC_LABEL,
                "source": SOURCE,
                "vintage": OEWS_RELEASE,
                "method": notes,
            }
        )

    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    log(f"wrote {len(rows)} of {len(cities)} cities to {output_path}")
    if len(rows) != len(cities):
        missing = sorted(
            f"{city['name']}, {city['state']}"
            for city in cities
            if not any(row["city"] == city["name"] and row["state"] == city["state"] for row in rows)
        )
        log(f"INCOMPLETE: {len(missing)} cities have no row: {', '.join(missing)}")
        if unfetched:
            log(f"INCOMPLETE: {unfetched} OEWS series were never fetched (daily allowance).")
            log("INCOMPLETE: rerun this script to fetch only those; the rest is cached.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cities", nargs="?", type=Path, default=DEFAULT_CITIES)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.cities.exists():
        log(f"error: city list not found at {args.cities}")
        log("Pass the path to thermal-indices/cities.json from modelhome/thermofeel-bundles.")
        return 1
    try:
        return build(args.cities, args.output)
    except (urllib.error.URLError, RuntimeError, OSError) as exc:
        log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

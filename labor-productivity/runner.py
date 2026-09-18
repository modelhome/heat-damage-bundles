#!/usr/bin/env python3
"""
Model Home runner: outdoor-worker heat damage from a thermal-indices table.

Reads a `thermal-indices` `heat_indices` artifact - `{metadata, columns, rows}`,
one row per city per day - and for each row computes the physical work capacity
an outdoor worker loses to that day's peak WBGT, then values the loss in dollars
using a committed BLS workforce and wage table.

    python runner.py HEAT_INDICES [LABOR_SUMMARY [LABOR_OPTIONS]]

- ``HEAT_INDICES``  the upstream artifact (default: the bundled sample).
- ``LABOR_SUMMARY`` where the per-city summary is written
                    (default: run/labor_summary.output.json).
- ``LABOR_OPTIONS`` optional `{erf, work_intensity_class, assumed_exposed_hours}`
                    (default: the values below). Missing, empty and null all
                    mean "use the default", so the model runs standalone or
                    composed.

It writes:

- stdout: the long-format table as JSON (the ``labor_damage`` output; the
  Modelfile redirects stdout to run/labor_damage.output.json);
- LABOR_SUMMARY: the same values per city, with the sampled damage curve, for a
  map-and-trend page (``labor_summary``);
- labor_damage.csv beside the summary. Model Home keeps only JSON outputs, so
  that file exists only when the model is run off-platform.

Nothing here touches the network: given the input artifact and the committed
tables, the output is exactly reproducible. Logs go to stderr; stdout carries
only the result.

What is exact and what is an estimate: `capacity_loss_pct` is the exposure-
response function evaluated at the day's peak WBGT, so it is peak-hour capacity
loss and nothing more. The hours and dollars scale that by
`assumed_exposed_hours` of the workday spent near that peak, which is a stated
assumption, not a measurement. See the README.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import erf

HERE = Path(__file__).resolve().parent
BLS_TABLE_PATH = HERE / "bls_labor.csv"
DEFAULT_INPUT_PATH = HERE / "sample_heat_indices.json"
DEFAULT_SUMMARY_PATH = Path("run") / "labor_summary.output.json"

# How much of the workday is spent near the daily peak WBGT. The single biggest
# lever on every dollar figure here, and a modelling choice rather than a
# published constant: the afternoon half of a nominal 8-hour outdoor shift.
DEFAULT_ASSUMED_EXPOSED_HOURS = 4.0
DEFAULT_WORK_INTENSITY_CLASS = "heavy"

# Presentation bands over capacity lost, for a map legend. Not a standard, unlike
# thermal-indices' NIOSH-derived work/rest categories.
RISK_BANDS = (
    (10.0, "safe"),
    (25.0, "reduced"),
    (50.0, "high"),
    (float("inf"), "severe"),
)

TABLE_COLUMNS = [
    "city",
    "state",
    "lat",
    "lon",
    "date",
    "is_forecast",
    "wbgt_c",
    "wbgt_source",
    "erf",
    "work_intensity_class",
    "assumed_exposed_hours",
    "work_capacity_pct",
    "capacity_loss_pct",
    "labor_risk_category",
    "exposed_workers",
    "mean_hourly_wage_usd",
    "labor_hours_lost",
    "dollar_loss_usd",
]

REQUIRED_ROW_KEYS = ("city", "state", "lat", "lon", "date", "is_forecast")


class RunError(Exception):
    """A problem that should fail the run with a readable reason."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def blank(value: object) -> bool:
    """True when a value means "not supplied" - absent, null or empty string."""
    return value is None or (isinstance(value, str) and not value.strip())


def parse_options(spec: dict) -> tuple[str, str, float]:
    """Resolve the run's parameters, defaulting anything absent or empty."""
    chosen_erf = spec.get("erf")
    chosen_erf = erf.DEFAULT_ERF if blank(chosen_erf) else str(chosen_erf)
    if chosen_erf not in erf.ERFS:
        raise RunError(
            f"unknown erf {chosen_erf!r}; choose one of {', '.join(sorted(erf.ERFS))}"
        )

    intensity = spec.get("work_intensity_class")
    intensity = DEFAULT_WORK_INTENSITY_CLASS if blank(intensity) else str(intensity).lower()
    if intensity not in erf.SUPPORTED_WORK_INTENSITY_CLASSES:
        raise RunError(
            f"work_intensity_class {intensity!r} is not supported: both implemented "
            f"exposure-response functions describe heavy outdoor work "
            f"({erf.WORK_INTENSITY_METABOLIC_RATE_W} W) and neither is parameterised by "
            f"metabolic rate. Supported: "
            f"{', '.join(erf.SUPPORTED_WORK_INTENSITY_CLASSES)}. See the bundle README."
        )

    hours = spec.get("assumed_exposed_hours")
    hours = DEFAULT_ASSUMED_EXPOSED_HOURS if blank(hours) else hours
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        raise RunError(f"assumed_exposed_hours must be a number, got {hours!r}") from None
    if not 0.0 < hours <= 24.0:
        raise RunError(f"assumed_exposed_hours must be above 0 and at most 24, got {hours}")

    return chosen_erf, intensity, hours


def load_json(path: Path, what: str) -> dict:
    try:
        with open(path) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise RunError(f"{what} not found at {path}") from None
    except json.JSONDecodeError as exc:
        raise RunError(f"{what} at {path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise RunError(f"{what} at {path} must be a JSON object, got {type(data).__name__}")
    return data


def parse_heat_indices(document: dict, path: Path) -> list[dict]:
    """Pull the rows out of a thermal-indices heat_indices artifact."""
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RunError(
            f"{path} does not look like a thermal-indices 'heat_indices' artifact: "
            "expected a non-empty 'rows' array. If this is a 'heat_summary' artifact "
            "(cities[].today / cities[].history), wire the flow to 'heat_indices' instead."
        )
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RunError(f"{path}: row {index} is not an object")
        missing = [key for key in REQUIRED_ROW_KEYS if key not in row]
        if missing:
            raise RunError(f"{path}: row {index} is missing {', '.join(missing)}")
        if "wbgt_c" not in row and "wbgt_simple_c" not in row:
            raise RunError(f"{path}: row {index} carries neither wbgt_c nor wbgt_simple_c")
    return rows


def load_bls_table() -> dict[tuple[str, str], dict]:
    if not BLS_TABLE_PATH.exists():
        raise RunError(f"the committed BLS table is missing at {BLS_TABLE_PATH}")
    table: dict[tuple[str, str], dict] = {}
    with open(BLS_TABLE_PATH, newline="") as fh:
        for entry in csv.DictReader(fh):
            table[(entry["city"], entry["state"])] = {
                "exposed_workers": int(entry["exposed_workers"]),
                "mean_hourly_wage_usd": float(entry["mean_hourly_wage_usd"]),
                "vintage": entry["vintage"],
                "source": entry["source"],
                "soc_codes": entry["soc_codes"],
            }
    if not table:
        raise RunError(f"the committed BLS table at {BLS_TABLE_PATH} has no rows")
    return table


def risk_category(capacity_loss: float) -> str:
    for threshold, label in RISK_BANDS:
        if capacity_loss < threshold:
            return label
    return RISK_BANDS[-1][1]


def driver_wbgt(row: dict) -> tuple[float | None, str | None]:
    """The WBGT to drive the ERF with, and where it came from."""
    liljegren = row.get("wbgt_c")
    if isinstance(liljegren, (int, float)):
        return float(liljegren), "liljegren"
    simple = row.get("wbgt_simple_c")
    if isinstance(simple, (int, float)):
        return float(simple), "simple"
    return None, None


def damage_rows(
    source_rows: list[dict],
    bls: dict[tuple[str, str], dict],
    chosen_erf: str,
    intensity: str,
    hours: float,
    warnings: list[str],
) -> list[dict]:
    # Only curves that state a fitted range can be extrapolated beyond it; a
    # curve that saturates by construction (Dunne) declares no range.
    valid_range = erf.ERFS[chosen_erf]["valid_range_c"]
    out_of_range: list[float] = []
    no_wbgt = 0
    unpriced_cities: set[str] = set()
    rows: list[dict] = []

    for source in source_rows:
        wbgt, source_name = driver_wbgt(source)
        economics = bls.get((source["city"], source["state"]))

        row = {
            "city": source["city"],
            "state": source["state"],
            "lat": source["lat"],
            "lon": source["lon"],
            "date": source["date"],
            "is_forecast": source["is_forecast"],
            "wbgt_c": round(wbgt, 2) if wbgt is not None else None,
            "wbgt_source": source_name,
            "erf": chosen_erf,
            "work_intensity_class": intensity,
            "assumed_exposed_hours": hours,
            "work_capacity_pct": None,
            "capacity_loss_pct": None,
            "labor_risk_category": None,
            "exposed_workers": economics["exposed_workers"] if economics else None,
            "mean_hourly_wage_usd": economics["mean_hourly_wage_usd"] if economics else None,
            "labor_hours_lost": None,
            "dollar_loss_usd": None,
        }

        if wbgt is None:
            no_wbgt += 1
            rows.append(row)
            continue

        if valid_range is not None and not valid_range[0] <= wbgt <= valid_range[1]:
            out_of_range.append(wbgt)

        loss = erf.capacity_loss_pct(wbgt, chosen_erf)
        row["capacity_loss_pct"] = round(loss, 3)
        row["work_capacity_pct"] = round(100.0 - loss, 3)
        row["labor_risk_category"] = risk_category(loss)

        if economics is None:
            unpriced_cities.add(f"{source['city']}, {source['state']}")
        else:
            # Value the hours that are actually published, not an unrounded
            # intermediate, so the three columns reconcile for anyone who checks
            # them by hand or in a spreadsheet.
            hours_lost = round((loss / 100.0) * economics["exposed_workers"] * hours, 2)
            row["labor_hours_lost"] = hours_lost
            row["dollar_loss_usd"] = round(hours_lost * economics["mean_hourly_wage_usd"], 2)

        rows.append(row)

    if no_wbgt:
        warnings.append(
            f"{no_wbgt} rows carried neither wbgt_c nor wbgt_simple_c; "
            "their capacity loss and dollar estimate are null"
        )
    if out_of_range:
        warnings.append(
            f"{len(out_of_range)} rows had a peak WBGT outside {chosen_erf}'s stated validity "
            f"range of {valid_range[0]}-{valid_range[1]} degC (seen {min(out_of_range):.1f} to "
            f"{max(out_of_range):.1f} degC); those values are extrapolated"
        )
    if unpriced_cities:
        warnings.append(
            f"{len(unpriced_cities)} cities are not in the committed BLS table, so their "
            f"hours and dollars are null: {', '.join(sorted(unpriced_cities))}"
        )
    return rows


def run_metadata(
    source: dict,
    chosen_erf: str,
    intensity: str,
    hours: float,
    bls: dict[tuple[str, str], dict],
    row_count: int,
    warnings: list[str],
) -> dict:
    entry = erf.ERFS[chosen_erf]
    any_city = next(iter(bls.values()))
    upstream = source.get("metadata") or {}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "erf": chosen_erf,
        "erf_citation": entry["citation"],
        "erf_summary": entry["summary"],
        "erf_valid_range_c": list(entry["valid_range_c"]) if entry["valid_range_c"] else None,
        "work_intensity_class": intensity,
        "metabolic_rate_w": erf.WORK_INTENSITY_METABOLIC_RATE_W,
        "assumed_exposed_hours": hours,
        "bls_source": any_city["source"],
        "bls_vintage": any_city["vintage"],
        "soc_codes": any_city["soc_codes"],
        "cities_in_bls_table": len(bls),
        "rows": row_count,
        "upstream": {
            "date": upstream.get("date"),
            "retrieved_at": upstream.get("retrieved_at"),
            "data_source": upstream.get("data_source"),
            "thermofeel_version": upstream.get("thermofeel_version"),
        },
        "assumptions": [
            "capacity_loss_pct is the exposure-response function evaluated at the day's "
            "peak WBGT, so it is peak-hour capacity loss, not a whole-day average.",
            f"labor_hours_lost and dollar_loss_usd assume {hours} hours of the workday are "
            "spent near that peak. That is a stated modelling choice, not a measurement, "
            "and every dollar figure scales linearly with it.",
            "Both implemented exposure-response functions describe heavy outdoor work "
            f"({erf.WORK_INTENSITY_METABOLIC_RATE_W} W); neither is parameterised by "
            "metabolic rate.",
            "Dollar figures are as of the BLS table's vintage and are not inflated to the "
            "run date.",
            "is_forecast and any preliminary-data caveat are inherited from the upstream "
            "thermal-indices run, not introduced here.",
        ],
        "warnings": warnings,
    }


def summary_document(metadata: dict, rows: list[dict], chosen_erf: str) -> dict:
    per_city: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["city"], row["state"])
        entry = per_city.setdefault(
            key,
            {
                "city": row["city"],
                "state": row["state"],
                "lat": row["lat"],
                "lon": row["lon"],
                "exposed_workers": row["exposed_workers"],
                "mean_hourly_wage_usd": row["mean_hourly_wage_usd"],
                "history": [],
            },
        )
        entry["history"].append(
            {key_: row[key_] for key_ in TABLE_COLUMNS if key_ not in ("city", "state", "lat", "lon")}
        )

    cities = []
    for entry in per_city.values():
        entry["history"].sort(key=lambda item: item["date"])
        entry["today"] = entry["history"][-1]
        cities.append(entry)

    return {
        "generated_at": metadata["generated_at"],
        "date": max(row["date"] for row in rows),
        "erf": chosen_erf,
        "erf_citation": metadata["erf_citation"],
        "erf_summary": metadata["erf_summary"],
        "work_intensity_class": metadata["work_intensity_class"],
        "assumed_exposed_hours": metadata["assumed_exposed_hours"],
        "bls_vintage": metadata["bls_vintage"],
        "window_days": max(len(city["history"]) for city in cities),
        "curve": erf.sample_curve(chosen_erf),
        "cities": cities,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT_PATH
    summary_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SUMMARY_PATH
    options_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    try:
        source = load_json(input_path, "the thermal-indices artifact")
        source_rows = parse_heat_indices(source, input_path)
        # A missing options file means the same as an empty one: use the
        # defaults. The settings are optional by design, so the model runs the
        # same whether it is invoked standalone or as a flow step.
        options = {}
        if options_path is not None:
            if options_path.exists():
                options = load_json(options_path, "the options file")
            else:
                log(f"no options file at {options_path}; using the defaults")
        chosen_erf, intensity, hours = parse_options(options)
        bls = load_bls_table()

        log(
            f"{len(source_rows)} rows, erf={chosen_erf}, work={intensity}, "
            f"exposed_hours={hours}"
        )
        warnings: list[str] = []
        rows = damage_rows(source_rows, bls, chosen_erf, intensity, hours, warnings)
        metadata = run_metadata(source, chosen_erf, intensity, hours, bls, len(rows), warnings)
    except RunError as exc:
        log(f"error: {exc}")
        return 1
    except OSError as exc:
        log(f"error: {exc}")
        return 1

    for warning in warnings:
        log(f"warning: {warning}")

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    # Compact JSON, as thermal-indices does: 89 cities x 30 days is ~2,700 rows,
    # which indentation would roughly double.
    compact = {"separators": (",", ":")}
    summary_path.write_text(
        json.dumps(summary_document(metadata, rows, chosen_erf), **compact) + "\n"
    )
    write_csv(summary_path.parent / "labor_damage.csv", rows)
    print(json.dumps({"metadata": metadata, "columns": TABLE_COLUMNS, "rows": rows}, **compact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

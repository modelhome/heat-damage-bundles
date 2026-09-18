#!/usr/bin/env python3
"""Validation for the labor-productivity bundle. Not in the Docker image.

Three modes, each exiting non-zero on the first failure:

    python check_erf.py                      the exposure-response functions
    python check_erf.py --table              the committed BLS table
    python check_erf.py --output IDX DMG SUM the outputs of a real run

The ERF checks compare each implementation against values published in its own
source paper. They are the evidence for AC-5; "it looks about right" is not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import erf

HERE = Path(__file__).resolve().parent
BLS_TABLE_PATH = HERE / "bls_labor.csv"

TOLERANCE_PP = 0.5  # percentage points

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  ok    {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))
        failures.append(label)


def close(actual: float, expected: float, tolerance: float = TOLERANCE_PP) -> bool:
    return abs(actual - expected) <= tolerance


# --- the exposure-response functions -----------------------------------------

# Foster et al. (2021) Table 3, WBGT row, evaluated from the published sigmoid.
# These are exact evaluations of the equation, cross-checked against a published
# restatement of the same curve, so the tolerance is tight.
FOSTER_PWC_POINTS = [
    (25.0, 87.0),
    (30.0, 67.0),
    (33.63, 50.0),
    (35.0, 44.0),
    (40.0, 25.0),
]

# Dunne, Stouffer and John (2013). The endpoints are the paper's own statement of
# its standards basis: full capacity to WBGT 25 degC, none at or above 33 degC.
DUNNE_CAPACITY_POINTS = [
    (20.0, 100.0),
    (25.0, 100.0),
    (27.0, 60.3),
    (29.0, 37.0),
    (31.0, 17.4),
    (33.0, 0.0),
    (36.0, 0.0),
]


def check_erfs() -> None:
    print("Foster et al. (2021): PWC% = 100/(1 + (WBGT/33.63)^6.33), valid 12-40 degC")
    for wbgt, expected_pwc in FOSTER_PWC_POINTS:
        actual_pwc = 100.0 - erf.foster2021(wbgt)
        check(
            f"WBGT {wbgt:>5} degC -> PWC {expected_pwc:.1f}%",
            close(actual_pwc, expected_pwc),
            f"got {actual_pwc:.2f}%",
        )

    # Informational, not an assertion. The paper's abstract says "we noted 10%
    # reductions in PWC at mild heat stress (WBGT = 18 degC) and reductions of 78%
    # in the most extreme conditions (WBGT = 40 degC)". The published WBGT equation
    # does not reproduce the first of those; see the bundle README.
    loss_18 = erf.foster2021(18.0)
    loss_40 = erf.foster2021(40.0)
    print(
        f"  note  abstract quotes 10% lost at WBGT 18 degC and 78% at 40 degC; "
        f"the equation gives {loss_18:.1f}% and {loss_40:.1f}%"
    )

    print("Dunne, Stouffer and John (2013): capacity = 100 - 25*max(0, WBGT-25)^(2/3)")
    for wbgt, expected_capacity in DUNNE_CAPACITY_POINTS:
        actual_capacity = 100.0 - erf.dunne2013(wbgt)
        check(
            f"WBGT {wbgt:>5} degC -> capacity {expected_capacity:.1f}%",
            close(actual_capacity, expected_capacity),
            f"got {actual_capacity:.2f}%",
        )

    print("Curve sampling and registry")
    for name in sorted(erf.ERFS):
        curve = erf.sample_curve(name)
        check(
            f"{name}: curve covers {erf.CURVE_START_C}-{erf.CURVE_STOP_C} degC "
            f"at {erf.CURVE_STEP_C} degC steps",
            len(curve) == 61
            and curve[0]["wbgt_c"] == erf.CURVE_START_C
            and curve[-1]["wbgt_c"] == erf.CURVE_STOP_C,
            f"{len(curve)} points",
        )
        check(
            f"{name}: loss is monotonic and within 0-100%",
            all(0.0 <= point["capacity_loss_pct"] <= 100.0 for point in curve)
            and all(
                curve[i]["capacity_loss_pct"] <= curve[i + 1]["capacity_loss_pct"] + 1e-9
                for i in range(len(curve) - 1)
            ),
        )
        check(f"{name}: has a citation", bool(erf.ERFS[name]["citation"]))

    check(
        "the two curves differ materially at 33 degC",
        abs(erf.foster2021(33.0) - erf.dunne2013(33.0)) > 40.0,
        f"foster {erf.foster2021(33.0):.1f}% vs dunne {erf.dunne2013(33.0):.1f}%",
    )

    try:
        erf.capacity_loss_pct(30.0, "no-such-curve")
    except ValueError:
        check("an unknown erf name is rejected", True)
    else:
        check("an unknown erf name is rejected", False)


# --- the committed BLS table -------------------------------------------------


def load_table() -> list[dict[str, str]]:
    import csv

    with open(BLS_TABLE_PATH, newline="") as fh:
        return list(csv.DictReader(fh))


def check_table(cities_path: Path | None) -> None:
    print(f"BLS table: {BLS_TABLE_PATH.name}")
    rows = load_table()
    check("table is non-empty", bool(rows), f"{len(rows)} cities")

    keyed = {(row["city"], row["state"]) for row in rows}
    check("no duplicate city/state keys", len(keyed) == len(rows))

    positive_workers = all(int(row["exposed_workers"]) > 0 for row in rows)
    positive_wages = all(float(row["mean_hourly_wage_usd"]) > 0 for row in rows)
    check("every city has a positive exposed-worker count", positive_workers)
    check("every city has a positive mean hourly wage", positive_wages)

    wages = [float(row["mean_hourly_wage_usd"]) for row in rows]
    check(
        "mean hourly wages are plausible (10-80 USD)",
        all(10.0 <= wage <= 80.0 for wage in wages),
        f"{min(wages):.2f}-{max(wages):.2f}",
    )

    check("every row names its source and vintage", all(row["source"] and row["vintage"] for row in rows))
    check("every row records how its area was matched", all(row["method"] for row in rows))

    if cities_path is not None and cities_path.exists():
        upstream = json.loads(cities_path.read_text())
        missing = sorted(
            f"{city['name']}, {city['state']}"
            for city in upstream
            if (city["name"], city["state"]) not in keyed
        )
        check(
            f"every city in {cities_path.name} is keyed in the table",
            not missing,
            f"{len(upstream)} upstream cities; missing: {missing[:5]}" if missing else f"{len(upstream)} cities",
        )
    else:
        print("  note  upstream cities.json not given; city-coverage check skipped")


# --- the outputs of a real run -----------------------------------------------


def check_output(input_path: Path, damage_path: Path, summary_path: Path) -> None:
    source = json.loads(input_path.read_text())
    damage = json.loads(damage_path.read_text())
    summary = json.loads(summary_path.read_text())

    print(f"Outputs: {damage_path.name}, {summary_path.name}")

    check(
        "one output row per input row",
        len(damage["rows"]) == len(source["rows"]),
        f"{len(damage['rows'])} out of {len(source['rows'])} in",
    )
    check(
        "city and date are preserved row for row",
        all(
            out["city"] == src["city"] and out["date"] == src["date"]
            for out, src in zip(damage["rows"], source["rows"])
        ),
    )
    check(
        "is_forecast is echoed, not recomputed",
        all(
            out["is_forecast"] == src["is_forecast"]
            for out, src in zip(damage["rows"], source["rows"])
        ),
    )
    check(
        "every declared column is present on every row",
        all(set(row) == set(damage["columns"]) for row in damage["rows"]),
    )

    priced = [row for row in damage["rows"] if row["dollar_loss_usd"] is not None]
    check("at least one row carries a dollar estimate", bool(priced), f"{len(priced)} rows")
    check(
        "capacity loss is within 0-100% wherever it is computed",
        all(
            0.0 <= row["capacity_loss_pct"] <= 100.0
            for row in damage["rows"]
            if row["capacity_loss_pct"] is not None
        ),
    )
    check(
        "work capacity and capacity loss sum to 100",
        all(
            abs(row["work_capacity_pct"] + row["capacity_loss_pct"] - 100.0) < 1e-6
            for row in damage["rows"]
            if row["capacity_loss_pct"] is not None
        ),
    )
    check(
        "dollar loss equals hours lost times the wage",
        all(
            abs(row["dollar_loss_usd"] - row["labor_hours_lost"] * row["mean_hourly_wage_usd"])
            < 0.01
            for row in priced
        ),
    )
    check(
        "wbgt_source is liljegren or simple on every priced row",
        all(row["wbgt_source"] in ("liljegren", "simple") for row in damage["rows"]),
    )

    city_count = len({(row["city"], row["state"]) for row in source["rows"]})
    check(
        "the summary carries every city",
        len(summary["cities"]) == city_count,
        f"{len(summary['cities'])} cities",
    )
    days_per_city = len(source["rows"]) // city_count
    check(
        "each city's history carries the whole window",
        all(len(city["history"]) == days_per_city for city in summary["cities"]),
        f"{days_per_city} days per city",
    )
    check(
        "each city's today is the newest history entry",
        all(city["today"] == city["history"][-1] for city in summary["cities"]),
    )
    check(
        "the summary carries the sampled curve",
        len(summary.get("curve", [])) == 61,
        f"{len(summary.get('curve', []))} points",
    )
    check(
        "the summary carries run-level ERF metadata",
        all(
            summary.get(key)
            for key in ("generated_at", "erf", "erf_citation", "work_intensity_class")
        ),
        f"erf={summary.get('erf')}",
    )
    check(
        "the summary's curve matches the ERF the run used",
        summary["curve"] == erf.sample_curve(summary["erf"]),
    )
    check(
        "assumed_exposed_hours is stated in the summary",
        isinstance(summary.get("assumed_exposed_hours"), (int, float)),
        f"{summary.get('assumed_exposed_hours')} h",
    )


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--table":
        cities = Path(argv[1]) if len(argv) > 1 else None
        check_table(cities)
    elif argv and argv[0] == "--output":
        if len(argv) != 4:
            print("usage: check_erf.py --output SAMPLE_INPUT LABOR_DAMAGE LABOR_SUMMARY", file=sys.stderr)
            return 2
        check_output(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    elif argv:
        print(f"unknown argument {argv[0]!r}", file=sys.stderr)
        return 2
    else:
        check_erfs()

    print()
    if failures:
        print(f"{len(failures)} of {checks} checks FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"all {checks} checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

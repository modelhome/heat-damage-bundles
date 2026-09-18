# Plan: Labor productivity

Source brief: docs/features/0001-labor-productivity.md
Status: blocked — implemented and locally verified except AC-6 (the BLS table covers 83 of 89
cities; the last six need one more BLS API query than the keyless daily allowance permitted) and
AC-8 (the Model Home import and the two-node flow have not been exercised yet)
Planned against commit: `c01c67c` (`main`, pushed to `modelhome/heat-damage-bundles`: top-level
boilerplate + vendored feat, no bundle yet)
Base commit: `f7829d0` (branch `feat/0001-labor-productivity`)

## Outcome

A `labor-productivity/` bundle in `modelhome/heat-damage-bundles`: a self-contained, offline
Model Home model that reads a `thermal-indices` `heat_indices` table (daily-peak WBGT per city
per day, 89 cities x 30 days) and returns, per city per day, the physical work capacity an
outdoor worker loses to that heat under a selected exposure-response function, plus an estimated
dollar value of the labour lost from a committed BLS workforce-and-wage table. It runs with no
network, so a rerun on the same input is byte-identical. Adding the folder's GitHub URL on Model
Home produces a model that composes after `thermal-indices` in a two-node flow.

## Scope

### In scope

As in the brief: the `labor-productivity/` bundle (Modelfile, Dockerfile, runner, sample input,
committed BLS table and its build script, committed ERF validation check, bundle README), the
top-level README bundle-table row, and the `CLAUDE.md` bundle section.

### Out of scope

As in the brief: the flow definition itself (it lives in the platform; there is no Flowfile), the
SPA and `damagefunction.com`, the sibling bundles, and any change to `thermal-indices` or to
platform code. Also out of scope for this plan and recorded as follow-ups: hourly or
workday-mean WBGT upstream (D9), indoor work and air-conditioning adjustment, acclimatisation
state as a parameter, and any occupation-level wage weighting finer than one mean wage per city
(D11).

## Review answers (John, 2026-09-17)

Asked before this plan was written, because each one changes what gets built:

- **Q1 — Which upstream artifact:** `heat_indices`, the flat table. See D1.
- **Q2 — Foster's WBGT-18 reference point:** assert the curve's own published values; record the
  abstract's discrepancy in the README rather than trying to reproduce it. See D5.
- **Q3 — The alternate ERF:** try LCHCC at implementation time, fall back to Hothaps if the
  parameters cannot be sourced from a primary document. See D6.
- **Q4 — The GitHub repo:** create it public and push `main`. Done: the scaffold commit `c01c67c`
  is on [`modelhome/heat-damage-bundles`](https://github.com/modelhome/heat-damage-bundles).

## Assumptions and decisions

### D1 — The flow handoff: `heat_indices`, bound by name (answers Q1, the brief's blocking question)

Verified in the `modelhome` repo at planning time, not assumed:

- Every artifact in a run, input or output, is a JSON file in one shared run directory named
  `<name>.output.json` (`orchestration/modelfile/command.py: map_host_artifact`). Binding step
  2's input to step 1's output **copies that file** under the downstream input's own name
  (`orchestration/engine.py: materialize_input_bindings`). The downstream runner therefore reads
  its `{input:NAME}` path and gets the upstream JSON **verbatim** — there is no envelope, no
  re-wrapping, and no CSV anywhere in the handoff.
- Bindings connect **by shape, not by name**. `check_schema_compatibility`
  (`orchestration/modelfile/validation.py`) runs both when the flow is saved
  (`backend/app/services/flow_service.py: _normalize_steps`) and when the bindings are
  materialised. It recurses into object `properties` and array `items`, requires the downstream
  input's `required` set to be a **subset** of the upstream output's, and compares declared types
  by equality with a single widening (a `number` input accepts an `integer` output).
- If a step's input name equals a previous step's output name, the flow **auto-wires** with no
  mapping at all (`raw_binding = {"source_step_index": index, "source_artifact": input_name}`).

So: this bundle declares an input named **`heat_indices`**, whose schema mirrors
`thermal-indices`' `heat_indices` output declaration — `{metadata, columns, rows}` with
`rows.items` an object. It declares as `required` **only the keys it actually reads**:
`city, state, lat, lon, date, is_forecast, wbgt_c, wbgt_simple_c`. All eight are in the upstream
output's 25-key required list, so the subset rule passes; declaring more would couple this model
to columns it does not use and would break the day `thermal-indices` drops one.

Rejected: `heat_summary`. It carries the same values, but its schema declares `today` as a bare
`object` and `history` as a bare `array` with no `items` type, so the compatibility check can
only confirm the outer shape — a mis-wiring would surface as an opaque container failure mid-run
instead of an error in the flow editor. `heat_indices` is also what the upstream Modelfile's own
comment nominates: "the table downstream damage-function models read".

### D2 — Parameters reach the model through a second input, `labor_options`

A non-first flow step must have **every** declared input bound; an unmapped, unmatched input
fails flow validation. But the flow editor offers each input either a step reference or a typed
value (URL or inline JSON) — `frontend/src/pages/FlowEditor.tsx` maps a JSON value to
`{inline: ...}`, and `flow_service.py` accepts it. So a second input works, and is the only shape
that lets the ERF be chosen *in a flow*:

```toml
[[inputs]]
name = "labor_options"   # required = [], default = {}
```

with `erf`, `work_intensity_class` and `assumed_exposed_hours` as optional properties, every
default living in the runner. Standalone, it is omitted entirely; in a flow, the author pastes
`{}` (or real options) into the second input's value box. The README and the Modelfile
description say this in one sentence, because it is the one piece of flow wiring a user has to do
by hand.

Rejected: folding the options into the single `heat_indices` input. It would validate (unknown
properties are not compared), but when bound from upstream the file *is* the upstream artifact,
so no option key could ever be present and the ERF would be unselectable in a flow — the exact
case the brief calls a showcase.

### D3 — Two JSON outputs, plus an off-platform CSV

Mirrors `thermal-indices` exactly, for the reason the brief already records: the platform keeps
only `/run/<name>.output.json`.

- **`labor_damage`** — the long-format table, `{metadata, columns, rows}`, one row per (city,
  date) across the full window. Comes from the stdout redirect in `run`.
- **`labor_summary`** — the nested per-city view (`cities[].today` + `cities[].history[30]`) with
  the labour fields, plus `generated_at`, `erf`, `erf_citation`, `work_intensity_class`,
  `assumed_exposed_hours`, `bls_vintage` and the sampled `curve`. Written by the runner to the
  `{output:labor_summary}` path.
- **`labor_damage.csv`** — the same columns as `labor_damage`, written beside the summary. The
  README states plainly that this file exists only when the model is run off-platform.

Output names are deliberately different from the input name: an input may not take over a name
another step produces (`_step_already_producing`), and `labor_*` keeps the flow's artifact
namespace unambiguous.

### D4 — The window and the city set pass through unchanged

Rows are echoed one-for-one: every (city, date) in the input produces exactly one output row, in
the same order. The city set is whatever the input carries — 89 on the default upstream run, 4 on
the sample. `is_forecast` is echoed, never recomputed. A city with no BLS table entry still gets
its physiology columns; the economics columns are null and the city is named in
`metadata.warnings` (D12).

### D5 — Foster et al. (2021) as the default ERF (answers Q2)

From Table 3 of Foster, Smallcombe, Hodder, Jay, Flouris, Nybo & Havenith (2021), "An advanced
empirical model for quantifying the impact of heat and climate change on human physical work
capacity", *Int J Biometeorol* 65:1215-1229, doi:10.1007/s00484-021-02105-0:

```
PWC% = 100 / (1 + (WBGT / 33.63) ** 6.33)          valid 12-40 C WBGT;  R2 = .94, RMSE = 5.94
capacity_loss_pct = 100 - PWC%
```

The sigmoid is the paper's general form `PWC% = 100/(1 + (x/PWC50)^HillSlope)` with fixed
plateaus at 0 and 100; 33.63 is PWC50 and 6.33 the HillSlope for WBGT. PWC is expressed relative
to a cool reference condition (15 C, 50% RH), and the underlying protocol is fixed cardiovascular
strain at a heart-rate ceiling of 130 b/min, which the paper characterises as moderate-to-heavy
occupational work.

**The validation targets are the curve's own values**, computed from the equation and
cross-checked against a second published restatement of it:

| WBGT (C) | 25 | 30 | 33.63 | 35 | 40 |
|---|---|---|---|---|---|
| PWC % | 87 | 67 | 50 | 44 | 25 |

Tolerance 0.5 percentage points (these are exact evaluations of the equation, not fits).

**Recorded discrepancy.** The paper's abstract says "we noted 10% reductions in PWC at mild heat
stress (WBGT = 18 C) and reductions of 78% in the most extreme conditions (WBGT = 40 C)". The
published WBGT equation gives 98.1% PWC at 18 C — a 1.9% reduction, not 10% — and a 75.0%
reduction at 40 C against the abstract's 78%. The 40 C figure is within rounding of the observed
extreme; the 18 C figure is not reproducible from this equation and most likely refers to the
observed data or to one of the air-temperature/clothing variants in supplementary Tables S1-S2.
Per Q2 the check asserts the equation, and the README quotes the abstract beside the computed
value so a reader who arrives via the abstract is not confused. `check_erf.py` prints the 18 C
value as an informational line, not an assertion.

### D6 — The alternate ERF: LCHCC, falling back to Hothaps (answers Q3)

The Lancet Countdown labour-capacity indicator uses a cumulative-normal exposure-response
function defined at three ISO work intensities — 200 W (light), 300 W (moderate) and 400 W
(heavy, outdoor construction and agriculture). The parameters were **not** obtainable from any
openly reachable primary source during planning; secondary sources restate the shape and quote
outcomes (for example 36% capacity loss at 30 C WBGT and 68% at 32 C for heavy outdoor labour)
without the coefficients.

Implementation step, in order, stopping at the first that yields citable parameters:

1. The Lancet Countdown annual report's methods appendix for the labour-capacity indicator
   (Romanello et al.; the 2024 and 2025 reports both carry it).
2. Bröde, Fiala, Lemke & Kjellstrom (2018), "Estimated work ability in warm outdoor environments
   depends on the chosen heat stress assessment metric", *Int J Biometeorol* 62:331-345,
   doi:10.1007/s00484-017-1346-9, which is the function's usual citation.
3. Failing both, implement **Hothaps** (Kjellstrom et al.) from its published two-parameter
   logistic form instead, name it `hothaps` rather than `lchcc`, and say in the README why LCHCC
   is absent.

Whichever lands, it is selectable as `erf` and validated against at least two published points of
its own source. `work_intensity_class` is meaningful only for this curve (D7).

### D7 — `work_intensity_class` is declared, and honest about Foster

Foster 2021 is a **single** curve at one cardiovascular-strain protocol; it is not parameterised
by metabolic rate. The LCHCC/Hothaps curve is, at 200/300/400 W. So:

- `work_intensity_class` accepts `light` (200 W), `moderate` (300 W) and `heavy` (400 W), and
  defaults to **`heavy` (400 W)** — outdoor construction and agriculture, which is the workforce
  the BLS SOC set counts (D10).
- Under `erf = "foster2021"` the class does not change the curve. The runner echoes the class in
  every row and states this in `metadata.assumptions`, the Modelfile `validity_domain` and the
  README, rather than silently ignoring it. It is not an error to set it.

This is the honest reading of the two papers and is worth John's eye at review: the alternative
would be to make Foster's low/high clothing-coverage variants (supplementary Tables S1-S2) the
configurable axis instead, which is a different parameter with a different meaning.

### D8 — The peak-WBGT exposure assumption

`thermal-indices` emits the daily **maximum** WBGT (and the local hour it occurred,
`wbgt_peak_hour_local`). So:

- `capacity_loss_pct` is exact: the ERF evaluated at that peak WBGT. It is peak-hour capacity
  loss and the README says so in those words.
- The daily estimate rests on `assumed_exposed_hours`, **defaulting to 4.0** — the afternoon half
  of a nominal 8-hour outdoor shift, the part that sits near peak WBGT. This is a recorded
  assumption, not a published constant; it is the single biggest lever on the dollar figure, it
  is overridable per run, and the README states both facts plainly.

```
labor_hours_lost = (capacity_loss_pct / 100) * exposed_workers * assumed_exposed_hours
dollar_loss_usd  = labor_hours_lost * mean_hourly_wage_usd
```

Every output description, the `validity_domain` and the README present the percentage as exact
and the dollars as an estimate.

### D9 — Recorded follow-up: hourly WBGT upstream

A `thermal-indices` enhancement emitting hourly (or workday-mean) WBGT would let this model
integrate loss across the workday and retire `assumed_exposed_hours` entirely. Out of scope here;
recorded in the bundle README's follow-ups and in `CLAUDE.md`'s task list so it reaches the
upstream repo.

### D10 — The BLS table

`build_bls_table.py` (committed, **not** in the image) builds `bls_labor.csv` from the BLS OEWS
metropolitan and nonmetropolitan area file — the May 2025 release,
`https://www.bls.gov/oes/special-requests/oesm25ma.zip`, the current vintage at planning time. No
API key; a single zipped workbook.

- **Heat-exposed outdoor SOC set** (a documented modelling choice, listed in full in the README):
  major group **47-0000** construction and extraction; major group **45-0000** farming, fishing
  and forestry; and **37-3011** landscaping and groundskeeping workers, plus the rest of the
  37-3000 grounds-maintenance minor group. Candidates deliberately excluded, with the reason
  given: 53-3032 heavy truck drivers (largely in-cab), 49-9021 HVAC installers (mixed), and all
  protective-service occupations.
- **Per city:** `exposed_workers` is the sum of OEWS `TOT_EMP` over that set for the city's area;
  `mean_hourly_wage_usd` is the employment-weighted mean of `H_MEAN` over the same set.
- **City -> area matching:** each of the 89 cities in `thermal-indices/cities.json` is matched to
  an OEWS `AREA` by name and state against `AREA_TITLE`. The crosswalk is committed **in the
  table itself** (`msa` and `method` columns), so a reader sees per city whether it was an exact
  MSA match, a nearest-MSA fallback, or a state-level fallback. Matching is done once, at build
  time, by a human-reviewable step — not heuristically at run time.
- **Suppression:** OEWS suppresses small cells (`**`, `#`). A suppressed occupation contributes 0
  employment and is excluded from the wage mean; the count of suppressed cells per city goes in
  the table's `method` column so the under-count is visible rather than silent.
- The script caches downloads under `.bls-cache/` (already in `.gitignore`); the table is
  committed and the runner only ever reads it.

### D11 — One mean wage per city, not per occupation

`dollar_loss_usd` uses one employment-weighted mean hourly wage per city rather than applying the
ERF per occupation. The ERF is not occupation-specific to begin with, so a finer wage split would
add precision the physiology does not have. Recorded as a follow-up.

### D12 — Failure and warning behaviour

- A row whose `wbgt_c` is null uses `wbgt_simple_c` and sets `wbgt_source = "simple"`; if both are
  null, the physiology and economics columns are null and the row is counted in
  `metadata.warnings`.
- A WBGT outside Foster's stated 12-40 C validity range is still evaluated (the sigmoid is
  well-behaved), but every such row is counted in `metadata.warnings` with the min and max seen,
  so extrapolation is visible.
- A city with no `bls_labor.csv` entry gets null economics and is named in `metadata.warnings`.
- A malformed input (not an object, no `rows`, a row missing a required key) exits non-zero with
  the reason on stderr. Warnings never fail the run; a structurally wrong input always does.

### D13 — No runtime dependencies

**This is a deviation from the brief's constraint, and it is deliberate.** The brief says to pin
numpy and pandas in the Dockerfile mirroring `thermal-indices`. But the runtime work here is
scalar arithmetic over a few thousand rows plus, for the cumulative-normal curve, a normal CDF —
which `math.erf` gives exactly. `csv`, `json` and `math` from the standard library cover
everything, so the image is `python:3.12-slim` with **no** `pip install` layer at all: smaller,
faster to build, and with nothing to drift. `build_bls_table.py` may use pandas/openpyxl to read
the OEWS workbook, and it never enters the image. The repo convention this follows is
`CLAUDE.md`'s "don't add a dependency when the standard library will do"; if John would rather
match `thermal-indices` byte-for-byte on this, say so at review and numpy goes back in.

### D14 — Risk bands

`labor_risk_category` from `capacity_loss_pct`: `safe` (< 10), `reduced` (10 to < 25), `high`
(25 to < 50), `severe` (>= 50). These are a presentation convention for the SPA, not a standard,
and the README says exactly that — unlike `thermal-indices`' `wbgt_work_category`, which comes
from the NIOSH REL.

### D15 — The sample input is generated, not written

AC-3 requires a *real* `thermal-indices` output. There is no committed one to copy
(`thermofeel-bundles/run/heat_indices.output.json` is an empty placeholder), so the sample is
produced once, at implementation time, by running the upstream runner — which needs network, for
that one build step only:

```sh
cd ~/repos/thermofeel-bundles
mkdir -p run
uv run --no-project --python 3.12 --with thermofeel==2.3.0 --with numpy==2.5.3 --with tzdata==2026.4 \
    python thermal-indices/runner.py thermal-indices/sample_input.json run/heat_summary.output.json \
    > run/heat_indices.output.json
```

That sample input is 2026-08-15 for Phoenix, Houston, Chicago and Minneapolis: 4 cities x 30 days
= 120 rows, small enough to commit and wide enough to exercise hot, humid, temperate and cold.
The result is committed verbatim as `labor-productivity/sample_heat_indices.json` — verbatim
matters, because it is also the evidence that the input contract is real.

## Deviations from this plan, recorded during `run`

1. **The alternate ERF is Dunne, Stouffer and John (2013), not LCHCC or Hothaps (changes D6).**
   The plan's chain was LCHCC, then Bröde et al. 2018, then Hothaps. None of the three yielded
   citable parameters from an openly reachable primary source: every paper that uses the
   cumulative-normal function cites it rather than reprinting its coefficients, and the same is
   true of Hothaps. Dunne 2013's function *is* fully specified in public sources and was
   cross-checked against two of them (NOAA GFDL's own summary of the paper, and the San Francisco
   Fed's restatement of the 25 degC / 33 degC endpoints). It is a standards-derived power law
   rather than a laboratory fit, which makes it a sharper contrast with Foster than LCHCC would
   have been. The brief listed "ISO 7243" as an acceptable further option and Dunne is built from
   exactly those occupational thresholds, so AC-5 is met on its own terms. The LCHCC slot stays
   open as a documented follow-up, with the two sources to chase named in the bundle README.
2. **`work_intensity_class` rejects unsupported values instead of ignoring them (changes D7).**
   With Dunne in place of LCHCC, *neither* implemented curve is parameterised by metabolic rate,
   so the plan's "declare it and document that Foster ignores it" would have shipped a setting
   that does nothing at all. Instead the runner accepts `heavy` and fails any other value with a
   message naming the limitation. The setting is now a validity-domain gate rather than a no-op,
   and it stays as the extension point for a work-intensity-aware curve.
3. **`valid_range_c` is `None` for Dunne (refines D12).** The plan warned on any WBGT outside the
   curve's stated range. Dunne's function is bounded by construction, not fitted over a range, so
   flagging its saturated values as "extrapolated" was simply wrong; only curves that state a
   fitted range now produce that warning. Foster keeps its 12-40 degC range.
4. **A missing options file means "use the defaults" (refines D2).** The runner first treated an
   absent `labor_options` file as an error. The settings are optional by design, so an absent file
   now behaves exactly like an empty one, with a note on stderr.
5. **Argument order is `HEAT_INDICES [LABOR_SUMMARY [LABOR_OPTIONS]]`.** The plan did not fix an
   order; this one keeps `thermal-indices`' shape (input, then where to write the summary) and
   appends the optional settings file, so the plan's own AC-3 command works unchanged.
6. **D13 (no runtime dependencies) held.** The image has no `pip install` layer at all.

## Acceptance-criteria traceability

IDs and wording preserved from the brief; none renumbered.

| ID | Acceptance criterion | Implementation | Verification | Status |
|---|---|---|---|---|
| AC-1 | Repo exists with top-level boilerplate and a `labor-productivity/` subfolder | `main` at `c01c67c`; bundle added on `feat/0001-labor-productivity` | [modelhome/heat-damage-bundles](https://github.com/modelhome/heat-damage-bundles) is public with `.gitignore`, `.dockerignore`, `LICENSE` (MIT), `README.md`, `CLAUDE.md` and `labor-productivity/` | **pass** |
| AC-2 | Bundle holds Modelfile, Dockerfile, runner, sample input, BLS table, BLS script | `labor-productivity/*` | all present, plus `erf.py` and `check_erf.py` | **pass** |
| AC-3 | Sample input is a real `thermal-indices` output; the runner runs end to end on it | `sample_heat_indices.json` (generated by the upstream runner, committed verbatim: 4 cities, 120 rows, 2026-07-17..2026-08-15, peak WBGT 20.1-36.5 degC), `runner.py` | the AC-3 command exits 0 and writes both outputs plus the CSV; `check_erf.py --output` 16/16 | **pass** |
| AC-4 | `docker build` succeeds; `docker run` reproduces identical outputs with no network | `Dockerfile` (no pip layer) | image builds; `docker run --network none` in the Modelfile's mounted layout gives rows identical to the local run; the bare default `CMD` also runs | **pass** |
| AC-5 | Foster 2021 matches its published reference points; an alternate ERF is selectable and changes the output | `erf.py`, `check_erf.py` | `check_erf.py` 20/20: Foster 87/67/50/44/25 % at 25/30/33.63/35/40 degC and Dunne 100 %/0 % at 25/33 degC, both within 0.5 pp; `{"erf":"dunne2013"}` changes every row (Phoenix 54.1 % -> 100 %) | **pass** (alternate curve is Dunne 2013, not LCHCC — deviation 1) |
| AC-6 | BLS table covers the same city set as `thermal-indices`, built by the committed script, documented | `build_bls_table.py`, `bls_labor.csv`, `README.md` | `check_erf.py --table` 7/8: the table is built by the script, every row has positive plausible employment and wages and records its source, vintage and match method — but it covers **83 of 89** cities | **blocked** — Juneau AK, Frankfort KY, Augusta ME, Concord NH, Montpelier VT and Pierre SD need state-level OEWS series, one query past the keyless BLS daily allowance. Everything else is cached; one rerun completes it |
| AC-7 | Output carries the full window per city; the JSON includes `curve` and run-level ERF metadata | `runner.py` | `check_erf.py --output`: 120 rows in, 120 out, 30-day history for each of 4 cities, `today` equals the newest entry, 61-point `curve` matching the run's ERF, ERF metadata present | **pass** |
| AC-8 | Pasting the subfolder GitHub URL into `/models/new/repo` creates a working model | `Modelfile.toml` | the Modelfile validates with no warnings, and the platform's own `check_schema_compatibility` confirms `labor_productivity.heat_indices <- thermal_indices.heat_indices` is compatible and auto-wires by name (and that `heat_summary` is correctly rejected) — but the import and the two-node flow have not been run on a live stack | **blocked** — not yet exercised on Model Home |
| AC-9 | README documents ERFs, work-intensity class, BLS source/vintage/SOC set, exposure assumption, determinism | `labor-productivity/README.md` | all nine items covered, including the Foster abstract discrepancy, the six missing cities, and the hourly-WBGT follow-up; `CLAUDE.md` and the top-level `README.md` updated | **pass** |

## Verification

The repo has no test harness and this plan does not invent one; the checks are the bundle's own
committed script plus the platform's Modelfile validator.

| Command | Purpose | Baseline result | Final result |
|---|---|---|---|
| `python labor-productivity/check_erf.py` | ERF equations match their published values (AC-5) | did not exist | **all 20 checks pass** |
| `python labor-productivity/check_erf.py --table <cities.json>` | BLS table covers the upstream city set (AC-6) | did not exist | **7 of 8 pass**; city coverage fails at 83/89 |
| `python labor-productivity/runner.py labor-productivity/sample_heat_indices.json run/labor_summary.output.json > run/labor_damage.output.json` | End-to-end run on a real upstream artifact (AC-3) | did not exist | **exit 0**, 120 rows, no warnings |
| `python labor-productivity/check_erf.py --output <input> <damage> <summary>` | Output schema, window pass-through, curve (AC-7) | did not exist | **all 16 checks pass** (1 genuine failure found and fixed first: dollars were derived from unrounded hours) |
| `cd labor-productivity && docker build -t heat-damage-labor-productivity:local .` | Image builds from the bundle folder as Model Home builds it (AC-4) | did not exist | **success** |
| `docker run --rm --network none -v "$PWD/run:/run" heat-damage-labor-productivity:local /run/heat_indices.output.json /run/labor_summary.output.json` | Offline reproducibility, identical to the local run (AC-4) | did not exist | **exit 0**, rows identical to the local run |
| `uv run python -m orchestration.modelfile validate .../labor-productivity/Modelfile.toml` | Modelfile is valid with no annotation warnings | n/a (no Modelfile) | **OK**, after trimming `validity_domain` to <= 600 and `provenance` to <= 400 characters |
| `check_schema_compatibility` against `thermal-indices`' Modelfile (platform code) | The flow binding is real, not assumed (AC-8 precursor) | n/a | **compatible** for `heat_indices`, correctly **incompatible** for `heat_summary`, auto-wires by name |

There is no pre-existing test harness in this repo, so every baseline is "did not exist"; no
pre-existing failure was inherited and none was masked.

## Implementation steps

1. **Generate and commit the sample input** (D15). Run the upstream runner for the four-city
   2026-08-15 sample; commit the `heat_indices` JSON verbatim as
   `labor-productivity/sample_heat_indices.json`. Record its row count and the WBGT range in the
   bundle README.
2. **`erf.py`** — the exposure-response functions, each with its citation in the docstring beside
   the equation. Foster 2021 first (D5). Pure functions of `(wbgt_c, work_intensity_class)`
   returning capacity loss in percent, plus a `sample_curve()` helper for the 15-45 C / 0.5 C
   sweep.
3. **`check_erf.py`** — assert the D5 table at 0.5 pp; print the 18 C value as information with
   the abstract quoted; fail loudly on any deviation. Run it before writing anything else that
   depends on the curve.
4. **Source the alternate ERF** (D6), in the order listed. Implement it, add its own published
   reference points to `check_erf.py`, and record in the plan's follow-ups which source supplied
   the parameters.
5. **`build_bls_table.py`** (D10) — download the OEWS May 2025 metro file, select the SOC set,
   aggregate per area, match the 89 cities, and write `bls_labor.csv` with `source`, `vintage`
   and per-city `method`. Review the matches by hand before committing the table; spot-check two
   or three cities against the BLS site.
6. **`check_erf.py --table`** — assert 89/89 cities, positive employment and wages, and no city
   in `cities.json` missing.
7. **`runner.py`** — read the input path (and optional options path) positionally, echo rows,
   evaluate the ERF, join the BLS table, apply D8, write the CSV, write `labor_summary` to the
   second positional arg, print `labor_damage` to stdout. Logs to stderr only. Compact JSON, as
   `thermal-indices` does.
8. **`check_erf.py --output`** — the AC-7 checks against a real run.
9. **`Modelfile.toml`** — inputs `heat_indices` (D1) and `labor_options` (D2); outputs
   `labor_damage` and `labor_summary` (D3); `run` redirecting stdout; the full annotation set
   (`determinism = "deterministic"`, `expected_runtime = "seconds"`, `validity_domain` carrying
   D5's 12-40 C range, D7's work-intensity caveat, D8's exposure assumption and D10's vintage;
   `not_for`; `provenance` with both citations and the BLS release). Validate with the platform
   validator; fix every warning.
10. **`Dockerfile`** (D13) — `python:3.12-slim`, `WORKDIR /app`, `COPY` the runner, `erf.py`,
    `bls_labor.csv` and the sample, `ENTRYPOINT`, `CMD` naming the sample. Build, then run with
    `--network none` and diff against the local run.
11. **`labor-productivity/README.md`** — the nine AC-9 items, in `thermal-indices/README.md`'s
    section order (Run it / Input / Outputs / Columns / Exposure-response functions / The
    economic layer / What is exact and what is an estimate / Determinism / Validation /
    Rebuilding the BLS table / Licences and attribution).
12. **Top-level `README.md` and `CLAUDE.md`** — the bundle-table row is already written against
    this design; confirm it still matches, and add the bundle's design notes, Modelfile notes,
    verified results and task list to `CLAUDE.md` in `thermofeel-bundles`' style.
13. **AC-8 on the local stack** — add the model from the branch subfolder URL, run it with the
    sample bound inline, then build the two-node flow (`thermal-indices` -> `labor-productivity`,
    auto-wired on `heat_indices`, `labor_options` bound inline as `{}`) and run it. Record what
    happened, including anything the flow editor made awkward.
14. **Open the pull request** with the brief, the plan and the bundle together. `run` stops there.

## Files likely to change

```
docs/features/0001-labor-productivity.md        (committed by run, already written)
docs/plans/0001-labor-productivity.md           (this file, updated with results)
README.md                                       bundle table row (already drafted)
CLAUDE.md                                       bundle section + task list
labor-productivity/Modelfile.toml               new
labor-productivity/Dockerfile                   new
labor-productivity/runner.py                    new
labor-productivity/erf.py                       new
labor-productivity/check_erf.py                 new
labor-productivity/build_bls_table.py           new
labor-productivity/bls_labor.csv                new (committed table)
labor-productivity/sample_heat_indices.json     new (real upstream output, D15)
labor-productivity/README.md                    new
```

## Risks and follow-ups

**Risks** (as built)

- **The alternate ERF's parameters could not be sourced** — this happened; see deviation 1. The
  curve shipped is Dunne 2013, which is fully cited and cross-checked, and the LCHCC slot stays
  open as a follow-up.
- **`assumed_exposed_hours = 4.0` is an assumption, not a finding** (D8). Every dollar figure
  scales linearly with it. It is documented in the README, the `validity_domain` and
  `metadata.assumptions`, and it is overridable per run — but a reader who quotes the dollars
  without the caveat is quoting a modelling choice. This is the single most important thing to
  say about this model.
- **The BLS table covers 83 of 89 cities** (AC-6). The six missing are state capitals with no
  MSA. They still get full physiology; their economics are null and they are named in
  `metadata.warnings`, so the gap is visible rather than silent.
- **The state-level OEWS area-code format is unverified.** `build_bls_table.py` builds it as
  `{FIPS}00000`, which is the documented BLS convention, but the daily allowance ran out before a
  live series could confirm it. If the rerun returns "series does not exist" for all six cities,
  that format is the first thing to check.
- **OEWS suppression under-counts small cities** (D10). One city in the table has a suppressed
  occupation group; the count travels in its `method` column.
- **City-to-MSA matching is the quiet failure mode** (D10). Mitigated by deriving it from the
  Census geocoder on the same coordinates `thermal-indices` uses, and by committing the matched
  MSA name and method per row so a reader can check it.
- **Foster's range is 12-40 degC** (D12). The committed sample tops out at 36.5 degC so it
  produces no extrapolation warning, but a full 89-city summer run will exceed 40 degC in Phoenix
  and those rows will be flagged.
- **AC-8 is unexercised.** The Modelfile validates and the flow binding is proven against the
  platform's own compatibility checker, but nothing has been imported into a running Model Home.

**Follow-ups (recorded, not built)**

- Hourly or workday-mean WBGT from `thermal-indices`, retiring `assumed_exposed_hours` (D9).
  Documented in the bundle README under "What is exact and what is an estimate".
- A work-intensity-aware curve (the LCHCC cumulative normal), which would make
  `work_intensity_class` mean something.
- Per-occupation wages instead of one city mean (D11).
- Indoor work and air-conditioning adjustment; acclimatisation as a parameter.
- The sibling bundles `heat-mortality/` and `cooling-demand/`, fanning out from the same
  `heat_indices` table.

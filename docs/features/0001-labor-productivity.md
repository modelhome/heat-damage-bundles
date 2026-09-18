# Labor productivity

## Outcome

`modelhome/heat-damage-bundles` has a `labor-productivity/` bundle: a self-contained Model Home
model that takes a `thermal-indices` output (daily-peak WBGT per city per day, across the
snapshot and the 30-day window) and returns, per city per day, the physical work capacity an
outdoor worker loses to that heat under a selected exposure-response function, plus an estimated
dollar value of the labour lost, using a committed BLS workforce-and-wage table.

This is the first damage-function model on Model Home. `thermal-indices`
(`modelhome/thermofeel-bundles`) is the hazard layer and stops at the indices; this is the
vulnerability layer that maps an index to a real-world loss. The two are composed into a
two-node flow, `thermal-indices -> labor-productivity`, created and run in the platform.

Pasting the subfolder's GitHub URL into the "build from your own repo" form at
`http://localhost:5173/models/new/repo` creates a working model. Its JSON output is shaped so
that a later SPA on `damagefunction.com` can draw the damage function the model used and plot
each city on it.

## Scope

### In scope

Repo-wide conventions are in the repo [`CLAUDE.md`](../../CLAUDE.md) and apply here without
being restated: mirror `thermofeel-bundles/thermal-indices/` and `QuantLib-bundles/bond/`;
implement each equation from its paper and cite it; validate against the paper's published
reference points; stay offline and deterministic at run time; pin everything; no emojis.

**Repo scaffold.** Top-level `.gitignore`, `.dockerignore`, `LICENSE` (MIT), `README.md` and
`CLAUDE.md`, matching `thermofeel-bundles`, plus the `labor-productivity/` bundle folder. The
top-level `README.md` bundle table lists `labor-productivity/` (inputs -> outputs) in the style
`thermal-indices` and `bond` use, and `CLAUDE.md` gains the bundle's design notes, Modelfile
format, verified results and task list.

**Bundle contents.** `labor-productivity/` holds `Modelfile.toml`, `Dockerfile`, `runner.py`, a
sample input JSON, the committed BLS table, the committed script that builds it, the committed
ERF validation check, and a `README.md`.

**Input contract.** The input is a `thermal-indices` output: model-2's input schema mirrors
model-1's output schema, so the two read as designed peers and the flow binding is exact.

- Which upstream artifact the flow passes, and in what shape, is settled in the plan before the
  parser is built (see Constraints). `thermal-indices` declares two JSON outputs: `heat_indices`
  (a long-format `{metadata, columns, rows}` table, one row per city per day, whose Modelfile
  comment calls it "the table downstream damage-function models read") and `heat_summary` (the
  same values nested as `cities[].today` + `cities[].history[30]`).
- The driver is `wbgt_c` (Liljegren, daily maximum). Where it is null, fall back to
  `wbgt_simple_c`, and record which was used per row in `wbgt_source` (`liljegren` | `simple`).
- The full city set and the whole snapshot-plus-30-day window pass through to this model's
  output, so a consumer gets a damage trend and not just today.

**Exposure-response functions.** WBGT in degrees C -> the fraction of physical work capacity
lost, for a given work-intensity class. At least two, implemented from the published equations
and cited in the code, the `Modelfile.toml` `provenance` and the README:

- **Foster et al. (2021)** — the default. The lab-derived physical work capacity model
  (Foster/Ioannou et al., "An advanced empirical model for quantifying the impact of heat and
  climate change on human physical work capacity"). Its published reference points are the
  validation targets: roughly 10% capacity lost at WBGT 18 C, 25-50% at 30-35 C, and 78% at
  40 C.
- **LCHCC / Lancet Countdown** — selectable. The cumulative-normal function defined for heavy
  (400 W), moderate (300 W) and light (200 W) work intensities in the Lancet Countdown methods
  (Romanello et al.). Implementing it lets the model reproduce the headline Lancet/ILO numbers,
  which is a deliberate demonstration that the curve is substitutable.
- **Hothaps (Kjellstrom)** and **ISO 7243** as further options if they are straightforward; drop
  either if it is not, and say so.

The ERF choice and the work-intensity class are declared, annotated parameters with documented
defaults (Foster 2021, and a stated outdoor work-intensity class with its metabolic-rate
assumption in W). Both are described in the Modelfile's `validity_domain`.

**Economic layer.** A committed script (`build_bls_table.py`) assembles, per city, the
heat-exposed outdoor workforce count and the mean hourly wage from BLS public data (OES
metropolitan employment and mean wage; QCEW if needed).

- The set of SOC occupation codes counted as heat-exposed outdoor labour is a documented
  modelling choice — construction and extraction (47-xxxx), farming, fishing and forestry
  (45-xxxx), grounds maintenance (37-3011) and similar. The README lists the exact set and why.
- The table keys to the same city set `thermal-indices` emits, each matched to its BLS
  metropolitan area. Where a city has no clean MSA match, a documented fallback (nearest MSA, or
  state-level) is used and recorded per city.
- Both the script and its output table are committed (`bls_labor.csv`:
  `city, state, msa, exposed_workers, mean_hourly_wage_usd, soc_codes, source, vintage, method`).
  The runtime model reads the committed table and never calls BLS.

**Loss translation.** `thermal-indices` emits the daily *peak* WBGT, not an hourly series, so
the exactly defensible physiological output is peak-hour capacity loss at that WBGT. Turning
that into a daily dollar figure needs an explicit assumption about how much of the workday sits
near peak stress.

- `capacity_loss_pct` is computed exactly from the peak WBGT through the selected ERF.
- The daily estimate uses a documented `assumed_exposed_hours` of the workday near peak WBGT:
  `labor_hours_lost = capacity_loss_pct x exposed_workers x assumed_exposed_hours`, and
  `dollar_loss_usd = labor_hours_lost x mean_hourly_wage_usd`.
- Every assumption is stated in the README and the Modelfile annotations. The peak-hour
  percentage is presented as exact; the dollar figure is presented as an estimate.

**Output** — the artifacts Model Home keeps are JSON (see Constraints); the CSV is written
alongside for off-platform use only. This schema is the contract a later SPA builds against.

1. **The table**, one row per (city, date) across the snapshot and the 30-day window, as JSON
   records with run metadata, and written as a CSV beside it when the model is run off-platform.
   Columns:
   - Identifiers and flags, echoed from the input: `city, state, lat, lon, date, is_forecast`
   - Driver: `wbgt_c`, `wbgt_source`
   - Parameters echoed: `erf`, `work_intensity_class`, `assumed_exposed_hours`
   - Physiology: `work_capacity_pct` (0-100, at peak WBGT), `capacity_loss_pct`,
     `labor_risk_category` (documented bands, e.g. safe / reduced / high / severe)
   - Economics: `exposed_workers`, `mean_hourly_wage_usd`, `labor_hours_lost`, `dollar_loss_usd`
2. **The per-city view**, mirroring `thermal-indices`' nested shape (`cities[].today` +
   `cities[].history[30]`) with the labour fields, plus run-level metadata: `generated_at`,
   `erf`, `erf_citation`, `work_intensity_class`, and a `curve` array — the selected ERF sampled
   across WBGT (15-45 C at 0.5 C steps) as `[{wbgt_c, capacity_loss_pct}]` — so a consumer can
   draw the exact damage function the model used and plot each city on it.

**Validation.** A committed check demonstrates that the Foster 2021 implementation matches its
published reference points within a stated tolerance, and that switching to the LCHCC curve
changes the output as expected.

**Documentation (README).** The ERFs and their citations; the default work-intensity class and
its metabolic-rate assumption; the BLS source, vintage, SOC set, MSA matching and fallbacks; the
peak-WBGT exposure assumption and how the dollar estimate follows from it; and the determinism
semantics — fully deterministic and offline, exactly reproducible given the input artifact and
the committed tables, with the dollar figures as-of the BLS table's vintage, and the
`is_forecast` flag and any preliminary-data caveat inherited from `thermal-indices` rather than
introduced here.

### Out of scope

- The flow definition (`thermal-indices -> labor-productivity`). It lives in the platform; there
  is no Flowfile.
- The SPA, and any `damagefunction.com` work.
- The sibling damage models (`heat-mortality/`, `cooling-demand/`).
- Any change to `thermal-indices` or to Model Home platform code. In particular, the
  `thermal-indices` enhancement that would emit hourly or workday-mean WBGT — which would let
  this model integrate loss across the workday properly instead of resting on
  `assumed_exposed_hours` — is recorded as a follow-up, not built here. If anything else here
  would benefit from an upstream change, record it the same way.

## Acceptance criteria

- **AC-1** — `modelhome/heat-damage-bundles` exists with top-level `.gitignore`,
  `.dockerignore`, `LICENSE` (MIT), `README.md`, `CLAUDE.md`, and a `labor-productivity/`
  subfolder, matching `thermofeel-bundles` conventions.
- **AC-2** — `labor-productivity/` contains `Modelfile.toml`, `Dockerfile`, `runner.py`, a
  sample input JSON, the committed BLS table, and the committed BLS-build script.
- **AC-3** — The sample input is a real (small) `thermal-indices` output — a few cities across
  the snapshot and window — committed so the model runs standalone.
  `python labor-productivity/runner.py labor-productivity/<sample_input>` runs end to end and
  writes the outputs with the schema above.
- **AC-4** — `docker build` from the bundle folder succeeds and `docker run` reproduces
  identical outputs with no network access.
- **AC-5** — The Foster 2021 ERF matches its published reference points within a stated
  tolerance (roughly 10% at WBGT 18 C, 25-50% at 30-35 C, 78% at 40 C); a committed check
  demonstrates this. At least one alternate ERF (LCHCC) is implemented and selectable, and
  switching ERFs changes the output as expected.
- **AC-6** — The BLS table covers the same city set as `thermal-indices`, built by the committed
  script, with the SOC set, source, vintage and per-city MSA matching (and any fallbacks)
  documented in the README.
- **AC-7** — The output carries the full snapshot and 30-day window per city, and the per-city
  JSON includes the sampled `curve` and the run-level ERF metadata.
- **AC-8** — Pasting the `labor-productivity/` subfolder GitHub URL into
  `http://localhost:5173/models/new/repo` creates a working model whose run produces the
  expected artifacts.
- **AC-9** — The README documents the ERFs and citations, the default work-intensity class and
  its metabolic assumption, the BLS source / vintage / SOC set / method, the peak-WBGT exposure
  assumption and how the dollar estimate is derived, and the determinism and offline semantics.

## Constraints and dependencies

- **Flow-handoff format (blocking for the plan).** The runner's input is whatever the platform
  passes from `thermal-indices`. Confirm the exact artifact and shape, from the platform's flow
  mechanics and the `thermal-indices` Modelfile output declarations, before building the parser,
  and mirror that output declaration in this model's input declaration. Settle in the same place
  how the model's parameters (ERF, work-intensity class, exposed hours) reach it when it runs as
  a flow step rather than standalone.
- **A CSV cannot be a Model Home output.** The platform collects only `/run/<name>.output.json`
  for each declared output and parses it as JSON; any other file a runner writes is discarded
  on-platform. `thermal-indices` already resolved this the same way: the long-format table is a
  JSON output, and a CSV with the same columns is written beside it for off-platform use only.
  This bundle follows that precedent rather than reopening it.
- **The city set is 89, not ~50.** `thermal-indices` ships `cities.json` with 89 cities (every
  state capital, the ten largest non-capital cities, and dry-heat, humid-heat, cold and mild
  examples). The BLS table must key to that set; a mismatch silently drops cities from the
  damage output.
- **No network at run time.** This is a pure function of its input plus the committed tables.
  BLS is fetched only by the one-time, committed build script. The sample run and `docker run`
  must both work offline.
- **Peak-WBGT limitation.** The input carries daily-peak WBGT, so the honest physiological
  output is peak-hour capacity loss, and the daily dollar figure rests on a documented
  workday-exposure assumption. Do not present the dollar figure as exact.
- **Provenance is published equations, not vendored code.** Implement each ERF from its paper
  and cite it; the bundle is MIT and vendors no third-party analysis code.
- **Pinned dependencies** in the Dockerfile, mirroring `thermal-indices`' pinning style (numpy,
  pandas, and whatever the ERFs need, each at an exact version).
- **Depends on** `modelhome/thermofeel-bundles`' `thermal-indices` bundle as the upstream model
  and the source of the input contract, the BLS OES (and possibly QCEW) public data releases,
  and `thermofeel-bundles` / `QuantLib-bundles` as the structural templates.

## General guidance

- Before you write the plan, ask any questions you need to in order to best implement the brief

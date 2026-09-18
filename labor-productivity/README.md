# labor-productivity: Heat Damage to Outdoor Work

Takes a day's heat and says what it costs the people who work outside.

The input is a [`thermal-indices`](https://github.com/modelhome/thermofeel-bundles/tree/main/thermal-indices)
table: one row per US city per day, carrying that day's peak Wet Bulb Globe
Temperature. For each row this model returns the share of physical work capacity
an outdoor worker loses to that heat, under a published exposure-response
function, and what the lost hours are worth, using a committed table of
construction, farming and grounds-keeping employment and wages from the BLS.

`thermal-indices` is the hazard layer and stops at the indices. This is the
vulnerability layer that turns an index into a loss. The two compose into a
two-node Model Home flow.

The model is a pure function: no network, no clock beyond the `generated_at`
stamp, no randomness. The same input and the same committed tables always give
the same numbers.

## Run it

```bash
# with Docker, from this folder (the build context, as on Model Home)
cd labor-productivity
docker build -t heat-damage-labor-productivity:local .
docker run --rm --network none heat-damage-labor-productivity:local   # bundled sample

# or directly with Python 3.12, from the repository root - no dependencies
mkdir -p run
python labor-productivity/runner.py labor-productivity/sample_heat_indices.json \
    run/labor_summary.output.json > run/labor_damage.output.json

# with a different damage curve
echo '{"erf": "dunne2013"}' > run/options.json
python labor-productivity/runner.py labor-productivity/sample_heat_indices.json \
    run/labor_summary.output.json run/options.json > run/labor_damage.output.json
```

On Model Home, paste this folder's GitHub URL
(`https://github.com/modelhome/heat-damage-bundles/tree/main/labor-productivity`)
into the "build from your own repo" option.

## Input

Two inputs.

**`heat_indices`** is the upstream table, passed straight through by the flow.
It is `{metadata, columns, rows}` with one object per city per day. This model
reads only eight columns and declares only those as required, so the flow keeps
working if `thermal-indices` changes a column it does not use:

| Column | Used for |
|---|---|
| `city`, `state` | the key into the workforce table |
| `lat`, `lon`, `date`, `is_forecast` | echoed to the output unchanged |
| `wbgt_c` | the driver: the day's peak WBGT (Liljegren) |
| `wbgt_simple_c` | the fallback, used only where `wbgt_c` is null |

Because the input is named `heat_indices`, exactly like the upstream output, a
flow wires the two together with no mapping at all.

**`labor_options`** holds the settings, all optional:

| Setting | Default | Meaning |
|---|---|---|
| `erf` | `foster2021` | which damage curve to use (`foster2021` or `dunne2013`) |
| `work_intensity_class` | `heavy` | how hard the work is; only `heavy` is available (see below) |
| `assumed_exposed_hours` | `4` | hours of the workday spent near the peak WBGT |

Missing, `null` and `""` all mean "use the default", so the model runs the same
standalone or composed. A flow step must bind every input, and this one has no
upstream to come from, so in the flow editor give it the value `{}` to accept
the defaults.

## Outputs

Two JSON outputs, because Model Home keeps only `<name>.output.json` for each
declared output and discards anything else a runner writes.

1. **`labor_damage`** — the long-format table, `{metadata, columns, rows}`, one
   row per city per day in the order the input carried them. Its `metadata`
   carries the curve and its citation, the work-intensity class and metabolic
   rate, `assumed_exposed_hours`, the BLS source, vintage and SOC codes, the
   upstream run's stamps, the stated assumptions, and any warnings.
2. **`labor_summary`** — the same values grouped by city (`cities[].today` and
   `cities[].history`), plus run-level metadata and `curve`: the chosen curve
   sampled from 15 to 45 degC WBGT at 0.5 degC steps, so a page can draw the
   exact damage function the run used and plot each city on it.

`labor_damage.csv` is written beside the summary with the same columns. It
exists only when the model is run off-platform; Model Home never sees it.

### Columns

| Column | Unit | Notes |
|---|---|---|
| `city`, `state`, `lat`, `lon`, `date`, `is_forecast` | | echoed from the input |
| `wbgt_c` | degC | the peak WBGT the curve was evaluated at |
| `wbgt_source` | | `liljegren`, or `simple` where the Liljegren value was missing |
| `erf`, `work_intensity_class`, `assumed_exposed_hours` | | the settings this row was computed under |
| `work_capacity_pct` | % | capacity remaining at the peak WBGT |
| `capacity_loss_pct` | % | capacity lost at the peak WBGT |
| `labor_risk_category` | | `safe`, `reduced`, `high` or `severe` |
| `exposed_workers` | | heat-exposed outdoor workers in the city's metro area |
| `mean_hourly_wage_usd` | USD/h | employment-weighted mean across those occupations |
| `labor_hours_lost` | h | `capacity_loss_pct` x `exposed_workers` x `assumed_exposed_hours` |
| `dollar_loss_usd` | USD | `labor_hours_lost` x `mean_hourly_wage_usd` |

Every column after `wbgt_source` is null on a row whose input carried no WBGT at
all; `exposed_workers` onwards are null for a city the workforce table does not
cover. Both cases are counted in `metadata.warnings` rather than passing
silently.

## The damage curves

Each curve is implemented directly from its paper, with the citation beside the
equation in [`erf.py`](./erf.py). No third-party analysis code is vendored.

### Foster et al. (2021) — the default

```
PWC% = 100 / (1 + (WBGT / 33.63) ** 6.33)
```

Foster J, Smallcombe JW, Hodder S, Jay O, Flouris AD, Nybo L, Havenith G (2021).
"An advanced empirical model for quantifying the impact of heat and climate
change on human physical work capacity." *International Journal of
Biometeorology* 65:1215-1229. [doi:10.1007/s00484-021-02105-0](https://doi.org/10.1007/s00484-021-02105-0)

Table 3, WBGT row: a sigmoid with plateaus fixed at 0 and 100%, PWC50 = 33.63
and HillSlope = 6.33, fitted to 338 work sessions in climatic chambers over
12-40 degC WBGT (R2 = .94, RMSE = 5.94). Capacity is relative to a cool
reference condition (15 degC, 50% RH), and the protocol holds cardiovascular
strain at a heart rate of 130 b/min, which the paper calls moderate-to-heavy
occupational work.

| WBGT (degC) | 25 | 30 | 33.63 | 35 | 40 |
|---|---|---|---|---|---|
| Work capacity (%) | 87 | 67 | 50 | 44 | 25 |

**One discrepancy, recorded rather than smoothed over.** The paper's abstract
says "we noted 10% reductions in PWC at mild heat stress (WBGT = 18 degC) and
reductions of 78% in the most extreme conditions (WBGT = 40 degC)". The
published WBGT equation gives a 1.9% reduction at 18 degC, not 10%, and 75.0% at
40 degC against the abstract's 78%. The 40 degC figure is within rounding of the
most extreme condition observed; the 18 degC figure is not reproducible from this
equation and most likely refers to the observed data or to one of the
air-temperature or clothing variants in the paper's supplementary tables. This
bundle implements and validates the published equation.
`check_erf.py` prints the 18 degC value as an informational line so the
difference is visible to anyone who arrives via the abstract.

### Dunne, Stouffer and John (2013)

```
work capacity % = 100 - 25 * max(0, WBGT - 25) ** (2/3),  bounded to 0-100
```

Dunne JP, Stouffer RJ, John JG (2013). "Reductions in labour capacity from heat
stress under climate warming." *Nature Climate Change* 3:563-566.
[doi:10.1038/nclimate1827](https://doi.org/10.1038/nclimate1827)

Derived from occupational safety thresholds for heavy work rather than from a
laboratory fit: full capacity up to WBGT 25 degC, and no safe outdoor work at or
above 33 degC, where the curve reaches zero exactly.

| WBGT (degC) | 25 | 27 | 29 | 31 | 33 |
|---|---|---|---|---|---|
| Work capacity (%) | 100 | 60.3 | 37.0 | 17.4 | 0 |

The two curves disagree sharply above 30 degC, and that is the point of having
both. On the bundled sample, Phoenix on 2026-08-15 (peak WBGT 34.5 degC) loses
54% of capacity under Foster and 100% under Dunne. Swapping the curve swaps
every downstream number, and `labor_summary.curve` always carries the curve the
run actually used, so a reader can see which one produced the figures in front
of them.

### Work intensity

`work_intensity_class` accepts only `heavy` (400 W, construction and
agriculture). Both implemented curves describe heavy outdoor work and neither is
parameterised by metabolic rate: Foster's is a single curve at one
cardiovascular-strain protocol, and Dunne's is built from the heavy-work
thresholds. Asking for `light` or `moderate` fails the run with that
explanation, rather than being quietly ignored.

The Lancet Countdown's cumulative-normal function, which *is* defined per work
intensity at 200, 300 and 400 W, would make this setting meaningful. Its
parameters were not obtainable from any openly reachable primary source while
this bundle was built; see the follow-ups below.

## The economic layer

[`bls_labor.csv`](./bls_labor.csv) is committed, and the runtime reads only that.
It is built by [`build_bls_table.py`](./build_bls_table.py), which is not in the
Docker image and is run by hand when the table needs refreshing.

**Source and vintage.** BLS Occupational Employment and Wage Statistics (OEWS),
**May 2025** release, read through the BLS public data API. All dollar figures
this model produces are as of that vintage and are not inflated to the run date.

**Which occupations.** The heat-exposed outdoor set is a modelling choice, not a
BLS category:

| SOC | Group |
|---|---|
| 47-0000 | Construction and extraction occupations |
| 45-0000 | Farming, fishing and forestry occupations |
| 37-3011 | Landscaping and groundskeeping workers |

Deliberately excluded, because their exposure is mixed or largely indoors:
53-3032 heavy truck drivers (mostly in-cab), 49-9021 HVAC installers, and all
protective-service occupations. `exposed_workers` is the sum of employment
across the set; `mean_hourly_wage_usd` is the employment-weighted mean of the
groups' mean hourly wages.

**Which metro area.** Each city's `lat`/`lon` — the same coordinates
`thermal-indices` uses — is resolved to a metropolitan statistical area through
the US Census Bureau geocoder, and that MSA's OEWS figures are used. The match
travels with each row in the table's `msa` and `method` columns, so a reader can
see per city how it was matched. A point that no MSA covers falls back to its
**state**, not to the nearest metro: the nearest metro can be hundreds of miles
away in a different labour market, which would produce a plausible-looking wrong
number.

**Coverage.** The table currently covers **83 of the 89 cities**
`thermal-indices` emits. Workforce sizes run from 1,720 (Carson City, NV) to
339,000 (New York, NY), and mean wages from $21.89 to $41.06 an hour. Six state
capitals with no MSA — Juneau AK, Frankfort KY, Augusta ME, Concord NH,
Montpelier VT and Pierre SD — are **missing**: their state-level figures need
one more BLS API query than the keyless daily allowance permitted on the day the
table was built. They still get full physiology; their `exposed_workers`,
`labor_hours_lost` and `dollar_loss_usd` are null and they are named in
`metadata.warnings`. Rerunning `build_bls_table.py` fetches only those; see
"Rebuilding the table" below.

OEWS suppresses small or unreliable cells. A suppressed occupation contributes no
workers and is left out of the wage mean, and the count is recorded in the row's
`method` column so the under-count is visible rather than silent.

## What is exact and what is an estimate

This matters more than any other line in this README.

`thermal-indices` emits the **daily peak** WBGT, not an hourly series. So:

- **`capacity_loss_pct` is exact** — it is the chosen curve evaluated at that
  peak WBGT. It is peak-hour capacity loss and nothing more. It is not a
  whole-day average, and reading it as one overstates the day.
- **`labor_hours_lost` and `dollar_loss_usd` are estimates.** They scale the
  peak-hour loss by `assumed_exposed_hours`, which defaults to **4** — the
  afternoon half of a nominal 8-hour outdoor shift. That is a stated modelling
  choice, not a measurement or a published constant, and every dollar figure
  scales linearly with it. Halve it and every dollar halves.

**Hourly WBGT would fix this.** If `thermal-indices` emitted hourly (or
workday-mean) WBGT instead of only the daily peak, this model could integrate
the loss across the workday properly and retire `assumed_exposed_hours`
altogether — the daily figure would then be as defensible as the peak-hour one,
and would rest on measured diurnal shape rather than on an assumption about it.
That is an enhancement to the upstream model, recorded here as a follow-up and
deliberately not built as part of this bundle.

## Risk bands

`labor_risk_category` reads `capacity_loss_pct` for a map legend:

| Band | Capacity lost |
|---|---|
| `safe` | under 10% |
| `reduced` | 10% to 25% |
| `high` | 25% to 50% |
| `severe` | 50% or more |

These are a presentation convention chosen here, not a safety standard — unlike
`thermal-indices`' `wbgt_work_category`, which comes from the NIOSH REL. Do not
use them to set anyone's work/rest schedule.

## Determinism

Fully deterministic and offline. Given the input artifact and the committed
`bls_labor.csv`, the output is exactly reproducible: there is no network call, no
randomness, and no wall-clock dependence beyond the `generated_at` stamp. The
`docker run --network none` verification below is the evidence.

Two caveats inherited rather than introduced: `is_forecast` and any
preliminary-data caveat come from the upstream `thermal-indices` run, and the
dollar figures are as of the BLS table's vintage.

## Validation

[`check_erf.py`](./check_erf.py) is the evidence, in three modes:

```bash
cd labor-productivity
python check_erf.py                       # the curves, against their papers
python check_erf.py --table ../../thermofeel-bundles/thermal-indices/cities.json
python check_erf.py --output sample_heat_indices.json \
    ../run/labor_damage.output.json ../run/labor_summary.output.json
```

The curve checks compare each implementation with values published in its own
source paper, to 0.5 percentage points, and assert that the two curves differ
materially where they should. The table checks assert coverage, positive and
plausible employment and wages, and that every upstream city is keyed. The output
checks assert that the window passes through row for row, that `is_forecast` is
echoed and not recomputed, that capacity and loss sum to 100, that the dollars
reconcile against the published hours and wage, and that the summary's `curve`
matches the curve the run actually used.

`sample_heat_indices.json` is a real `thermal-indices` output, committed verbatim:
2026-08-15 for Phoenix, Houston, Chicago and Minneapolis, 120 rows over the
30-day window, peak WBGT from 20.1 to 36.5 degC. It is the evidence that the
input contract is real rather than assumed.

## Rebuilding the table

```bash
cd labor-productivity
python build_bls_table.py ../../thermofeel-bundles/thermal-indices/cities.json
```

The script caches every Census and BLS response under `.bls-cache/`, so a rerun
costs nothing and an interrupted build resumes where it stopped rather than
starting over. Keyless, the BLS API allows 25 series per query and **25 queries
per day**, and this table needs 22 of them; set `BLS_API_KEY` to a free
[registration key](https://data.bls.gov/registrationEngine/) to raise that to 50
series and 500 queries. The script exits non-zero and names the missing cities
whenever the table is incomplete.

BLS blocks automated retrieval of the OEWS flat files at their edge (the
`oesm*ma.zip` downloads return 403 to any non-browser client), which is why the
build goes through the API rather than the published workbook.

## Follow-ups

- **Hourly WBGT upstream**, which would retire `assumed_exposed_hours` (above).
- **The six missing cities**, one BLS query away.
- **A work-intensity-aware curve.** The Lancet Countdown's cumulative-normal
  function is defined at 200, 300 and 400 W and would make
  `work_intensity_class` meaningful. Its parameters were not in any openly
  reachable primary source at build time; the candidates to chase are the Lancet
  Countdown report's methods appendix (Romanello et al.) and Bröde, Fiala, Lemke
  and Kjellstrom (2018), *Int J Biometeorol* 62:331-345,
  [doi:10.1007/s00484-017-1346-9](https://doi.org/10.1007/s00484-017-1346-9).
- **Per-occupation wages** instead of one employment-weighted mean per city.
- **Indoor work and air conditioning**, and acclimatisation as a parameter.

## Licences and attribution

This bundle is MIT, like the rest of the repository. The exposure-response
functions are implemented from their published equations and cited above; no
third-party analysis code is vendored.

- Employment and wages: US Bureau of Labor Statistics, Occupational Employment
  and Wage Statistics, May 2025. Public domain.
- Metro-area matching: US Census Bureau geocoder. Public domain.
- Heat input: the US Daily Heat Stress model in
  [modelhome/thermofeel-bundles](https://github.com/modelhome/thermofeel-bundles),
  which carries its own attribution for Open-Meteo and thermofeel.

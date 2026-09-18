# heat-damage-bundles

Standalone Model Home **model bundles** that turn heat hazard into damage. Each
bundle is a self-contained folder with everything Model Home needs to run one
model: a `Modelfile.toml`, a `Dockerfile`, a `runner.py`, and sample input(s).

Every bundle here is a **downstream** model. Its input is another model's
output — today, the `heat_indices` table from
[`modelhome/thermofeel-bundles`](https://github.com/modelhome/thermofeel-bundles)'s
`thermal-indices` bundle — and the two are composed in a Model Home flow. Design
each bundle so that its input schema mirrors the upstream output schema it
consumes; the two models should read as designed peers, not as one model
parsing another's file.

```
heat-damage-bundles/
  CLAUDE.md                 <- you are here
  README.md
  LICENSE                   (MIT)
  .claude/skills/feat/      <- vendored feat skill (brief -> plan -> PR workflow)
  docs/features/            <- feature briefs (NNNN-name.md)
  docs/plans/               <- implementation plans, one per brief
  <bundle>/                 <- one self-contained model per folder
```

The first bundle is `labor-productivity/`. Later siblings (`heat-mortality/`,
`cooling-demand/`) consume the same upstream table, turning the linear chain
into a fan-out: one hazard model feeding several damage models.

---

## The templates: `thermal-indices/` and `bond/`

[`modelhome/thermofeel-bundles`](https://github.com/modelhome/thermofeel-bundles)
(especially `thermal-indices/`) and
[`modelhome/QuantLib-bundles`](https://github.com/modelhome/QuantLib-bundles)
(especially `bond/`) are the authoritative templates. Read them before starting
a bundle and mirror them. Consistency across the bundles matters more than any
local preference:

- **`Modelfile.toml` keys.** `name`, `description`, `run`, `image`, `args`,
  `[resources]`, `[[inputs]]` with a documented `[inputs.schema]` (every
  property has a plain-language `description`; the schema's `default` is what
  the platform offers as the "Example to paste", so it must stay runnable), and
  `[[outputs]]` with `[outputs.schema]`. Plus the annotation fields Model Home
  validates: `determinism`, `expected_runtime`, `validity_domain`, `not_for`,
  `provenance`, and per-property `unit`. Rationale the schema cannot express
  goes in TOML comments beside it.
- **Runner I/O contract.** Input JSON file path(s) arrive as positional args.
  The result JSON goes to **stdout** and nothing else does — logs go to stderr.
  The Modelfile's `run` redirects stdout to `run/<output>.output.json`. Further
  outputs are passed as `{output:NAME}` args and written by the runner.
- **`required = []` and defaults in the runner.** A present-but-empty value
  (`""` or `null`) falls back the same way a missing key does, so the model runs
  standalone or composed.
- **Dockerfile.** `python:3.12-slim`, `WORKDIR /app`, exact `==` pins installed
  in one `pip install --no-cache-dir` layer, `COPY` paths relative to the bundle
  folder, `ENTRYPOINT ["python", "runner.py"]`, and a `CMD` naming the bundled
  sample input so a bare `docker run` works.

## Model Home platform facts (verified against the platform code)

- **Build context is the bundle subfolder.** Adding a model from
  `github.com/modelhome/heat-damage-bundles/tree/main/<bundle>` promotes that
  folder to the build-context root, exactly like `cd <bundle> && docker build .`.
  Never use repo-relative `COPY <bundle>/...` paths; the on-platform build fails.
- **Every output is a JSON file.** The platform collects only
  `/run/<name>.output.json` for each declared `[[outputs]]` name and parses it
  with `json.loads`. Any other file a runner writes (a CSV, a PNG) is discarded
  on-platform, so a CSV is an off-platform convenience only and can never be the
  artifact a flow passes on.
- **How a flow hands one model's output to the next.** Every artifact in a run,
  input or output, lives in one shared run directory as `<name>.output.json`
  (`orchestration/modelfile/command.py: map_host_artifact`). Binding step 2's
  input to step 1's output **copies the file** under the downstream input's own
  name, so the downstream runner just reads its `{input:NAME}` path and gets the
  upstream JSON verbatim. Consequences to design for:
  - **Connections are by shape, not by name.** `check_schema_compatibility`
    (`orchestration/modelfile/validation.py`) runs both when the flow is saved
    and when bindings are materialised. It recurses into object `properties` and
    array `items`, requires the downstream input's `required` keys to be a
    **subset** of the upstream output's, and compares declared types by equality
    with one widening (a `number` input accepts an `integer` output). So declare
    as required only the keys the bundle genuinely reads.
  - **A matching name auto-wires.** If a step's input name equals a previous
    step's output name, the flow needs no explicit mapping at all.
  - **Every input of a non-first step must be bound.** An unmapped, unmatched
    input fails flow validation. A parameters input that does not come from
    upstream is bound in the flow editor as an inline JSON value (or a URL);
    give it a schema `default` so there is something sensible to accept.
- **Model containers have outbound network access**, but a bundle here should
  not need it: see below.
- **A schedule re-sends a fixed input.** Anything that should change per run must
  be defaulted inside the runner, not baked into a schedule's stored input.

## Conventions for every bundle

- **Implement each equation from its paper, and cite it.** There is no upstream
  library to wrap here. Read the source paper for the exact functional form and
  coefficients rather than a summary of it, put the citation in the code beside
  the function, in the `Modelfile.toml` `provenance`, and in the bundle README.
  Do not vendor third-party analysis code; the bundle stays MIT.
- **Validate against the published reference points.** Each bundle commits a
  check that runs its equations at the values the paper states and compares.
  A committed check that passes is the evidence; "it looks about right" is not.
- **Offline and deterministic at run time.** These are pure functions of their
  input plus committed tables. Any data build (a BLS table, a lookup) happens
  once, in a committed script that is not in the image, and its output table is
  committed with a stated source, method and **vintage**. The runner makes no
  network calls, so a rerun on the same input is byte-identical. State the
  vintage in the README: the numbers are as-of it.
- **Inherit upstream caveats, don't invent new ones.** Flags such as
  `is_forecast` and any preliminary-data caveat come from the upstream hazard
  model. Echo them through rather than restating or relabelling them.
- **Be honest about what is exact and what is an estimate.** Where a documented
  modelling assumption (an exposure window, an occupation set) stands between a
  computed quantity and a headline number, say so in the README, in the
  `validity_domain` annotation, and in the wording of the output's descriptions.
- **Pin everything** in the Dockerfile. Don't add a dependency when numpy, the
  standard library, or an existing pin will do.
- **Readable over clever.** Inputs are small (tens of cities x weeks). Favour
  plain code.
- **No emojis** in source files.

## How features are built: `feat`

Features are developed from versioned briefs with the vendored
[`feat`](./.claude/skills/feat/SKILL.md) skill, so the brief, the plan and the
implementation land together in one pull request:

1. `/feat create <name>` scaffolds `docs/features/NNNN-<name>.md`. Hand-written
   briefs in the same template are fine.
2. `/feat plan <name>` writes `docs/plans/NNNN-<name>.md` and stops. John reviews
   and revises the plan before anything is built.
3. `/feat run <name>` implements the approved plan on `feat/NNNN-<name>` and
   stops at the pull request. It never merges, releases, or deploys.

Repo-wide conventions live in this file; briefs reference them rather than
restating them.

## Task list

1. ~~Scaffold the repo: top-level boilerplate and the vendored feat skill.~~
   Done 2026-09-17.
2. Create `modelhome/heat-damage-bundles` on GitHub and push `main` (awaiting
   John; `/feat run` needs the remote to open its pull request).
3. `labor-productivity/` (brief 0001): plan written, awaiting review.
4. Compose `thermal-indices -> labor-productivity` as a Model Home flow (in the
   platform; there is no Flowfile).
5. Later siblings: `heat-mortality/`, `cooling-demand/`.

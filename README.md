# heat-damage-bundles

Standalone [Model Home](https://modelhome.run) model bundles that turn heat
hazard into damage: given the thermal indices a hazard model produces, they
estimate what that heat costs. Each subfolder is a self-contained model: a
`Modelfile.toml`, a `Dockerfile`, a `runner.py`, and sample inputs.

These are the vulnerability layer that sits downstream of
[`modelhome/thermofeel-bundles`](https://github.com/modelhome/thermofeel-bundles).
Its `thermal-indices` model stops at the indices (it says how hot it feels);
the models here map those indices to a loss. The two are composed in a Model
Home flow.

Unlike `thermofeel-bundles`, there is no upstream library to wrap. The
exposure-response functions are published, peer-reviewed equations implemented
directly from their papers, with the citation carried in the code, the
`Modelfile.toml` and the bundle README.

## Bundles

| Bundle | Model | Inputs → Outputs |
|---|---|---|
| [`labor-productivity/`](./labor-productivity) | Outdoor-worker physical work capacity lost to heat, and what it costs | a `thermal-indices` daily table (WBGT per city per day) → per city per day: work capacity lost under a selected exposure-response function, labour hours lost and dollars of lost labour from a committed BLS workforce and wage table, plus the sampled damage curve |

## Quick start

```bash
# the build context is the bundle folder, the same one Model Home builds from
cd labor-productivity
docker build -t heat-damage-labor-productivity:local .
docker run --rm heat-damage-labor-productivity:local   # no network needed
```

Or, when creating a new model on Model Home, paste the bundle folder's GitHub
URL (for example
`https://github.com/modelhome/heat-damage-bundles/tree/main/labor-productivity`)
into the "build from your own repo" option.

Each bundle's README covers its inputs, outputs, equations, data sources and
assumptions. See [`CLAUDE.md`](./CLAUDE.md) for the design notes, the
conventions every bundle follows, verified results, and how features are
briefed, planned and built.

# to build and run from your local machine (build context is this
# labor-productivity/ folder, which is also what Model Home uses when the model is
# added from github.com/modelhome/heat-damage-bundles/tree/main/labor-productivity):
#   cd labor-productivity && docker build -t heat-damage-labor-productivity:local .
#   docker run --rm heat-damage-labor-productivity:local     # uses the bundled sample
#   mkdir -p run && cp sample_heat_indices.json run/heat_indices.output.json
#   docker run --rm -v "$PWD/run:/run" heat-damage-labor-productivity:local \
#       /run/heat_indices.output.json /run/labor_summary.output.json \
#       > run/labor_damage.output.json
# The model is a pure function of its input and the committed tables, so it needs
# no network at all: `docker run --network none` works and is how it is verified.

FROM python:3.12-slim

WORKDIR /app

# No pip layer on purpose. The runtime is scalar arithmetic over a few thousand
# rows plus a committed CSV, which csv, json and math already cover; adding numpy
# or pandas would only add something to drift. pandas belongs to
# build_bls_table.py, which is not in this image.

COPY runner.py erf.py bls_labor.csv sample_heat_indices.json ./

ENTRYPOINT ["python", "runner.py"]

# irl the input/output paths come from the Modelfile; for local testing we
# default to the bundled sample input.
CMD ["sample_heat_indices.json"]

# iact-perf

A community database of published Cherenkov telescope performances:
sensitivity, angular and energy resolution, effective area, background
rates... Every value comes from a published source and keeps a trace of
where and how it was taken.

Status: early development. The schema may still change.

## Layout

```
instruments/<id>.yaml          instruments and their configurations
references/crab_spectra.yaml   reference Crab spectra (to interpret values in C.U.)
references/analyses.yaml       analysis chains and productions (records name one)
sources/<slug>/
  source.yaml                  the publication: DOI or URL, type, ...
  <record>.ecsv                one value or curve of one quantity
  extract.py                   script that produced the records (optional)
schema/                        JSON Schema of the YAML files and record headers
```

A source slug reads `<instrument>_<firstauthor><year>_<topic>`, for example
`magic_aleksic2016_performance-upgrade`.

A record is an ECSV table with the columns `energy`, `energy_min`,
`energy_max`, `value`, `value_err_low`, `value_err_high` (with astropy
units) and a header under the key `iact_perf` describing the quantity, the
instrument configuration, the observation and analysis conditions, and the
provenance. Values are stored as published; for example a sensitivity in
"% C.U." keeps the unit `% CU` and names its reference Crab spectrum.

See [docs/design.md](docs/design.md) for the design decisions.

## Usage

```bash
uv sync
uv run iact-perf list --quantity sensitivity      # browse the records
uv run iact-perf validate                         # check every database file
uv run iact-perf reproduce                        # re-run the extractions, diff with the records
uv run pytest
```

```python
import iact_perf

db = iact_perf.load()
recs = db.query(
    quantity="sensitivity", instrument="magic", energy_integration="differential", zenith="20 deg"
)
rec = recs[0]
rec.table  # QTable with units, values as published
rec.meta.sensitivity_criteria  # how the sensitivity was defined
db.convert(rec, "erg cm-2 s-1")  # C.U. -> E^2 dN/dE with the record's Crab spectrum
db.summary()  # one row per record
db.query(instrument="ctao", analysis="freepact")  # by instrument and analysis
```

## Contributing a source

See [AGENTS.md](AGENTS.md): the step-by-step ingestion procedure, written for
humans and coding agents alike. Start with `uv run iact-perf new <slug>`.

## Licence

Data: CC-BY-4.0 (see LICENSE-DATA). When you use a value, cite its original
source first. Code: BSD-3-Clause.

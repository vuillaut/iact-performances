# User guide

`iact_perf` is a Python package that ships the database and lets you query it.
You get each value as it was published, its unit, and the conditions it was
obtained under. This page covers installation and the vocabulary. The how-to
pages solve one task each, and the [API reference](api.md) lists every
function and field.

## Install

The package needs Python 3.11 or later. It bundles the data, so a single
install gives you both the code and the records:

```bash
pip install git+https://github.com/vuillaut/iact-performances
```

If you work in a clone of the repository, `uv sync` installs it in editable
mode and `iact_perf.load()` reads the files of your checkout.

## First query

```python
import iact_perf

db = iact_perf.load()
print(db)

recs = db.query(
    instrument="ctao",
    analysis="prod6-official",
    quantity="sensitivity",
    zenith="20 deg",
    observation_time="50 h",
)
rec = recs[0]
print(rec.meta.label)
print(rec.table)
```

`rec.table` is an astropy `QTable`: every column carries its unit, and the
numbers are those of the source, in the unit of the source.

## Vocabulary

**Source.** One publication or data release: a paper, a proceedings, an
official IRF release. Its identifier is a slug,
`<instrument>_<firstauthor><year>_<topic>`, such as
`magic_aleksic2016_performance-upgrade`. `db.sources[slug]` gives its title,
authors, DOI and notes. Read the notes: they say what was extracted, what was
left out, and any known problem in the source.

**Record.** One value or one curve of one quantity, under one set of
conditions, from one source. A table with two zenith ranges and two
definitions of the angular resolution gives four records. Each record is an
ECSV file; its id is the file name without `.ecsv`.

**Instrument and configuration.** `instrument` is `ctao`, `magic`, `lst1`,
`hess`, ... A configuration is one way of operating the instrument: which
telescopes, mono or stereo, which hardware period or array layout.
`db.instruments["magic"].configurations` lists them.

**Analysis.** The analysis chain or production that made the curve:
`prod6-official`, `freepact`, `magic-mars-standard`, ... Two records with the
same instrument and different analyses are different results for the same
telescopes. `db.analyses` describes each one.

**Crab reference.** A sensitivity in Crab units (`% CU`) means nothing without
the Crab spectrum that defines the unit. Such records name it in
`crab_reference`, an id in `db.crab_spectra`. Some references are `observed`:
the unit is the Crab flux measured in the same data, and there is no absolute
flux to convert to.

**Superseded.** When a newer source replaces an older one, the older source
gets `superseded_by`. Both stay in the database. Queries leave superseded
records out unless you ask for them.

## The columns of a record

| Column | Content |
|---|---|
| `energy` | energy of each point; for an integral quantity, the threshold |
| `energy_min`, `energy_max` | bin edges, when the source gives bins |
| `value` | the published value |
| `value_err_low`, `value_err_high` | published errors, as positive sizes |

A column is present only if the source gives it. Many records have bin edges
and no `energy` column: `rec.energy` then returns the geometric bin centre,
which is convenient for plotting but is not a published number.

## The header of a record

`rec.meta` holds the metadata. The fields you will use most:

| Field | Meaning |
|---|---|
| `label` | one sentence describing the record |
| `quantity` | `sensitivity`, `angular_resolution`, `energy_resolution`, `energy_bias`, `effective_area`, `background_rate`, `gamma_rate`, `energy_threshold`, `field_of_view` |
| `definition` | how the quantity was computed: `containment_68` or `gaussian_sigma` for an angular resolution, `gaussian_sigma`, `rms` or `containment_68` for an energy resolution, ... |
| `energy_integration` | `differential` or `integral`, for sensitivities and rates |
| `energy_type` | `true` (Monte Carlo energy) or `reconstructed` |
| `data_kind` | `monte_carlo`, `real_data` or `mixed` |
| `observation_time` | observation time of a sensitivity; for IRF productions, the time the cuts were optimised for |
| `sensitivity_criteria` | significance, formula, minimum excess, minimum signal/background ratio, bins per decade |
| `conditions` | zenith range, azimuth, offset, Moon, cuts, analysis details |
| `provenance` | how and where the values were taken from the source: table or figure, label, original column |

A value of `"unknown"` means the source does not say. The database never
guesses it. Physical values are strings with a unit, such as `"50 h"` or
`"20 deg"`; pass them to `astropy.units.Quantity` to compute with them.

## How-to guides

- [Find records](how-to/find-records.md): filter by instrument, analysis,
  quantity, zenith, observation time, or any condition.
- [Plot a curve](how-to/plot.md): energy bins, error bars, several records on
  one figure.
- [Convert Crab units](how-to/crab-units.md): from `% CU` to a flux and back,
  and why some records refuse.
- [Compare results fairly](how-to/compare.md): check the conditions that make
  two curves comparable, or not.
- [Cite a value](how-to/cite.md): find the source, the table or figure, and
  the citation.
- [Use the data without the library](how-to/without-python.md): ECSV files,
  the JSON export, the JSON Schema, a local checkout.

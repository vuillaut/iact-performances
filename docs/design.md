# iact-perf: design

A community database of published Cherenkov telescope performances, so that
sensitivities, resolutions and other figures of merit can be compared across
instruments with full provenance.

## Scope

- v1 covers IACTs. The schema is built to accept other instrument types later
  (`type: IACT | WCD | space`).
- All usual IACT performance quantities: curves (differential and integral
  sensitivity, angular resolution, energy resolution and bias, effective area,
  ...) and scalars (energy threshold, field of view, ...).
- Only published values: collaboration papers, official IRF releases, and
  algorithm or analysis studies. We never store values we recomputed.
- Records are queried by instrument and by analysis (see below).
- We delete nothing. A replaced value is marked `superseded_by`; the library
  returns the most recent one by default.

## Data layout

```
instruments/
  magic.yaml               # instrument + configurations (mono/stereo, periods, sub-arrays)
sources/
  magic_aleksic2016_performance-upgrade/
    source.yaml            # DOI if any, else URL; source metadata
    angular_resolution_68_stereo_zd-lt-30.ecsv
    extract.py             # optional extraction script
```

### Source slug

`<instrument>_<firstauthor><year>_<topic>`: lowercase ASCII, hyphens inside the
topic. Examples: `magic_aleksic2016_performance-upgrade`,
`lst1_abe2023_performance`, `ctao_prod6-v1.0_performance`. For a
multi-instrument source, use the instrument it characterises. CI checks
format and uniqueness.

### `source.yaml`

- `schema_version`
- `doi` (publisher DOI preferred over the arXiv DOI) or `url` (+ access date)
- `arxiv` (optional), `ads_bibcode` (optional)
- `source_type`: `article | proceedings | irf_release | webpage | thesis | report`
- `refereed`: bool
- `superseded_by`: slug or null
- `reproducible`: bool. If true, `extract.py` is the entry point.

### Records

One record = one value or one curve of one quantity, taken from one source.
A source table holding several quantities is split into several records.

ECSV columns (astropy units):

| column | required |
|---|---|
| `energy` | for curves: `energy`, or the bin edges, or both |
| `energy_min`, `energy_max` | if binned |
| `value` | yes |
| `value_err_low`, `value_err_high` | if published or digitized |

Values are stored as published, with their unit, including scaled units such
as `1e-13 cm-2 s-1`. Crab units use the custom astropy unit `CU` (`% CU` for
"% C.U."), which astropy never converts on its own: a record in CU must name a
`crab_reference` from `references/crab_spectra.yaml`, and the library does
the conversion at read time. Error columns hold positive sizes.

Record metadata (ECSV `meta`):

- Required: `quantity` (`sensitivity`, `angular_resolution`, `energy_resolution`,
  `energy_bias`, `effective_area`, `background_rate`, `gamma_rate`,
  `energy_threshold`, `field_of_view`), `instrument`, `configuration`,
  `analysis`, `data_kind`
  (`monte_carlo | real_data`), `observation_time`, sensitivity criteria
  (significance, min. excess, signal/background requirement, bins per decade,
  differential/integral) when the quantity is a sensitivity.
- Optional, controlled vocabulary, `unknown` when not given in the source:
  zenith range, Moon conditions, offset, analysis details, cuts, energy type
  (true/reco), resolution definition (68 % containment / Gaussian sigma).
- `definition` for resolutions and bias (`containment_68`, `gaussian_sigma`, `rms`, ...).
- `energy_integration` (`differential | integral`) for sensitivities and rates.
  For an integral curve, `energy` is the threshold.
- `provenance`: `latex_table | pdf_table | vector_figure | raster_digitized | official_data_file`
- `original_column`, digitization uncertainty when relevant.

### Analyses

`analysis` is an id from `references/analyses.yaml`: the analysis chain or
production that made the curve (`magic-mars-standard`, `freepact`,
`prod5-official`, ...). Ids are shared across sources when the analysis is
the same, so that `db.query(instrument="ctao", analysis="prod5-official")`
gathers every Prod5 record. It also separates algorithm studies from
official productions of the same instrument.

## Extraction (semi-automatic)

Order of preference:

1. Official machine-readable files (Zenodo, collaboration web pages).
2. arXiv LaTeX sources: tables parsed from `.tex`, vector PDF figures read
   from their paths.
3. Raster digitization.

An optional LLM, behind a small provider-agnostic interface (Claude by
default), finds the performance figures and tables, identifies curves,
proposes metadata from the text and calibrates axes. Numbers always come
from deterministic code.

Vector figures are read with `iact_perf.extract.vector` (matplotlib PDF
output): panels found by their axis labels, axes calibrated on the labelled
ticks with an exact linear fit, curves identified by stroke colour and
checked against the legend. Points outside the visible axes are dropped:
the reader of the paper cannot see them. Coordinates are rounded to 6
significant digits. An overlay of the points on the figure is no check for
vector extraction (the points come from the drawn paths); the calibration is
checked against something it did not use: a twin axis, a number quoted in the
text. Contributors are responsible for checking their values.

`iact-perf reproduce <slug>` runs `extract.py` (Python only) in a temporary
directory and compares the output with the committed records. Contract: the
script defines `extract(out: Path, cache_dir: Path | None = None)`, downloads
its source into `cache_dir` (uncommitted) and writes every record into `out`.
A GitHub workflow runs all reproductions weekly and on demand.

## Library

`iact_perf.load()` returns a `Database` (instruments, sources, records,
Crab spectra). `Database.query()` filters by header fields, zenith,
observation time and supersession (superseded sources are left out by
default). `Database.convert()` changes units; for sensitivities it converts
between CU, dN/dE and E² dN/dE using the record's Crab spectrum: a
differential value in CU is relative to the Crab dN/dE at the point energy
(geometric bin centre when only edges are given), an integral value to the
Crab integral flux above the threshold. Both conventions reproduce the
absolute fluxes of the MAGIC tables to the rounding of the published digits.
The wheel bundles the data; `IACT_PERF_ROOT` points the library elsewhere.

## Repository and governance

- GitHub; contributions by pull request; one maintainer at start.
- CI: schema, units and slug validation. Extraction scripts are not run in
  CI; a manual or periodic job does that.
- Licences: data CC-BY-4.0, code BSD-3-Clause. `CITATION.cff` asks users to
  also cite the original source. No PDFs or figures committed.
- Releases: manual semver tags archived on Zenodo. Minor = new sources,
  major = incompatible schema change.

## Deliverables (v1)

- Python package `iact-perf` (uv, Python >= 3.11, pydantic with JSON Schema
  export, astropy, pytest, ruff): queries returning `QTable`s, comparison plots.
- Extraction CLI for contributors.
- Zensical site on GitHub Pages: one page per source, instrument and
  quantity, plus a Plotly.js comparison page reading a JSON export.
- Interoperability later: ctaplot reads its reference curves from here;
  sensitivity and resolutions exportable to gammapy.

## Seed sources

- MAGIC, Aleksić et al. 2016 (reuse `vuillaut/MAGIC_performances_2015_data_tables`).
- CTAO prod5 / prod6 official curves from the ROOT files (reuse code from
  `vuillaut/ctao-performances`).
- LST-1: Abe et al. 2023 and the performance page files.
- H.E.S.S.: a paper with vector figures.
- VERITAS: Park 2015 (ICRC).
- An old raster paper (HEGRA or Whipple).
- ctaplot reference curves, after checking their provenance.

`ctao-performances` and `MAGIC_performances_2015_data_tables` are code and
ideas to reuse, not dependencies or sources.

# Instructions for agents: ingesting a source

This repository is a database of **published** Cherenkov telescope
performances. Your usual task here is to ingest one source (a paper, a
proceedings, an IRF release, an official web page): turn its performance
values into validated records with full provenance.

Read `docs/design.md` once for the reasons behind the rules below. Two
sources show the two main extraction paths; read the one closest to yours
before you start:

- `sources/magic_aleksic2016_performance-upgrade/`: LaTeX tables.
- `sources/ctao_schwefer2024_freepact-reconstruction/`: vector figures.
- `sources/ctao_prod6-v1.0_performance/`: official data files (ROOT
  histograms in a Zenodo bundle).

## Ground rules

1. **Numbers come from code, never from your reading.** Every value is
   produced by `extract.py` from the original file (LaTeX table, data file,
   vector figure). Do not type numbers you read in a PDF or an image into a
   script. If there is no other way, stop and ask the human.
2. **Store values as published.** Same numbers, same unit, including scaled
   units (`1e-13 cm-2 s-1`) and Crab units (`% CU`). No conversion, no
   recomputed value. For figures, "as published" means what a reader sees:
   see [Figures](#figures).
3. **Never guess metadata.** If the source does not say, write `unknown`.
   A wrong zenith range or observation time is worse than `unknown`, because
   people will compare curves that are not comparable.
4. **Never commit the source itself.** No PDF, figure, tarball, FITS or ROOT
   file in the repository. Downloads go to the cache (`.cache/`, gitignored).
   Validation rejects these files.
5. **Never delete or overwrite published records of another source.** A
   newer result marks the old source with `superseded_by`; both stay.
6. **Published values only, never recomputed ones.** Any source that
   publishes performance values is in scope: collaboration papers, official
   IRF releases, but also algorithm or analysis studies. What is out of
   scope is a value that you (or the database) derived: a curve recomputed
   from IRFs, a fit, an interpolation, a bin centre. The `analysis` field
   tells users which analysis or production each record comes from.
7. **A check that finds nothing to check must fail.** If your script checks
   legend colours, axis ticks or row counts, make it raise when it finds no
   legend, no ticks or no rows. A check that passes on nothing hides bugs.

## Workflow

### 1. Identify the source

- Get the publisher DOI (preferred), the arXiv id and the ADS bibcode. No
  DOI: use the URL and the date you accessed it.
- Check it is not already in the database:
  `grep -r "<doi or arxiv id>" sources/*/source.yaml`.
- Check whether it replaces an earlier source (a new performance paper of
  the same configuration and analysis). If so, tell the human: they decide
  whether to set `superseded_by` on the older one.

### 2. Find the values and pick the extraction path

Inventory every performance value in the source (tables, figures, text),
then extract each from the best available form, in this order:

| Form | `provenance.method` | Tools |
|---|---|---|
| Official machine-readable file (Zenodo, collaboration page) | `official_data_file` | `iact_perf.extract.zenodo` (download + md5, archives read in memory), `.root` (uproot), `.eventdisplay` (CTAO IRF ROOT files) |
| Table in the arXiv LaTeX source | `latex_table` | `iact_perf.extract.latex` |
| Table in a PDF only | `pdf_table` | a PDF table parser called from `extract.py` |
| Vector figure (PDF/EPS paths) | `vector_figure` | `iact_perf.extract.vector` (matplotlib PDF figures) |
| Raster figure | `raster_digitized` | no shared tool yet: stop and ask |

When a value exists both in a table and in a figure, use the table.

Curves of *another* source drawn for comparison (e.g. the official Prod5
curves in a paper's figures) are not extracted with this source: they
belong to their own source. List them in `notes` as not extracted.

To explore an arXiv source, use `iact_perf.extract.arxiv.list_files(id)`
and `read_file(id, name)`: they read the tarball in memory. Do not unpack
archives. If you really need files on disk to look at them, unpack under
`.cache/<id>/`, never execute anything from there, and delete it when done.

### 3. Create the source directory

```bash
uv run iact-perf new <instrument>_<firstauthor><year>_<topic>
```

Slug rules: lowercase ASCII, three parts separated by `_`, hyphens inside a
part. The first part is the instrument the source characterises; it must be
an id in `instruments/`. Examples: `magic_aleksic2016_performance-upgrade`,
`lst1_abe2023_performance`, `ctao_prod6-v1.0_performance`.

Fill `source.yaml`: every `TODO` must go. In `notes`, say which tables and
figures you extracted, which you did not and why, and anything a user must
know (errata, known inconsistencies, points dropped).

### 4. Instrument and configuration

Each record names an `instrument` and a `configuration` from
`instruments/<id>.yaml`. A configuration is one way of operating the
instrument: which telescopes, mono or stereo, which hardware period or
array layout. Add the instrument file or a new configuration if needed. Do
not attach a record to a configuration that does not match (MAGIC data from
2010 do not belong to `stereo_upgraded`). Write only dates and facts you can
source; leave the rest out.

### 5. Analysis

Each record names an `analysis` from `references/analyses.yaml`: the
analysis chain or production that made the curve. Users query by
instrument *and* analysis (`db.query(instrument="ctao", analysis="freepact")`),
so choose ids a user would select or compare:

- **Reuse** an existing id when it is the same analysis: every record of the
  official CTAO Prod5 IRFs uses one `prod5-official`, whatever the source.
- **Add** an id for a new analysis: an algorithm (`freepact`, `impact`),
  a collaboration's standard chain (`magic-mars-standard`), a production
  (`prod6-alpha-layout`). Give a name, a description, and references.
- An id per paper is a smell: use it only for something specific to one
  paper, like an event selection shared by all its methods
  (`schwefer2024-event-selection`).

Free-text details (software versions, settings) go to
`conditions.analysis_details` of the record.

### 6. Crab reference

A value in Crab units needs `crab_reference`, an id in
`references/crab_spectra.yaml`. Find in the paper which Crab spectrum defines
its C.U. (its own fit, HEGRA 2004, H.E.S.S. 2006, ...). Add the spectrum
exactly as the cited paper writes it, with its reference. If the paper does
not say which spectrum it uses, do not pick one: stop and ask. A sensitivity
computed on Crab observations often has no model at all: its C.U. is the Crab
observed in the same data. With the human's agreement, record it as a
reference with `model: observed` (see `lst1_abe2023_observed`); such values
stay in C.U. and the library refuses to convert them to an absolute flux.

### 7. Write `extract.py`

Contract, checked by `iact-perf reproduce`:

```python
def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Download the source into cache_dir and write every record into out."""
```

- Download with the helpers (`iact_perf.extract.arxiv.get_tex`, `read_file`)
  or into `cache_dir` yourself.
- Write each record with `iact_perf.records.write_record(path, columns, meta)`.
  It refuses inconsistent records.
- Only Python. Deterministic: running it twice gives identical files.
- Put the checks of section 9 that can be automated **in the script**, so
  that they run again at every reproduction.
- Generic code (a parser, a reader) belongs in `src/iact_perf/extract/`
  with tests, not in one source's script. If you need it, propose it.

**Tables.** Locate a LaTeX table by its `\label` (`find_table`), split it
(`split_rows`), parse cells with `parse_cell` (handles `a \pm b` and
`a_{-l}^{+h}`) and `parse_range` (`47 - 75`). The script maps columns to
meanings: you write that mapping by reading the header and caption.

**One record = one quantity, one definition, one analysis, one set of
conditions.** A table with two zenith ranges and two resolution definitions
gives four records.

**Columns** (all with astropy units):

| column | content |
|---|---|
| `energy` | energy of each point; for an integral quantity, the threshold |
| `energy_min`, `energy_max` | bin edges, when the source gives bins |
| `value` | the published value |
| `value_err_low`, `value_err_high` | published errors, as **positive** sizes |

Give `energy` only if the source gives it; never compute a bin centre to
fill it. Leave error columns out when the source shows no errors.

**Record file names**: `<quantity>_<qualifiers>_<conditions>[_<analysis>].ecsv`,
lowercase, hyphens inside a part, e.g.
`angular_resolution_containment-68_zd00-30.ecsv`,
`energy_bias_mean_zd20-mst-subarray_freepact.ecsv`.

### Figures

`iact_perf.extract.vector.Figure(pdf_bytes, panel_labels)` reads a matplotlib
vector figure: it finds the panels by their y-axis labels, calibrates every
axis on its labelled ticks (the fit must be exact, or it raises), and
`Figure.curves(panel)` returns the curves by stroke colour. Rules:

- **Points outside the visible axes are dropped.** They are in the file but
  the reader of the paper cannot see them: they are not published values.
  `Figure.curves` drops them and counts them (`n_outside`); say so in `notes`.
- **Precision**: round the coordinates with `round_sig` (6 significant
  digits). The path coordinates carry float noise far below what a figure
  shows.
- **Errors**: extract error bars or bands only if the figure draws them.
- **Identify curves by legend, not by guess**: check every curve colour
  against `Figure.legend()`, and fail if the legend is missing.
- **Check the calibration independently.** An overlay of the extracted
  points on the figure is *not* a check for vector figures: the points come
  from the same paths as the drawn curves, so they always land on them. Use
  something the calibration did not use: a twin axis
  (`Figure.right_axis_ticks`, e.g. arcmin vs degrees), a number quoted in
  the text or a table of the same paper, a value at a known point. Write the
  check into `extract.py` when you can.

Raster figures need a digitizer with its own uncertainty
(`provenance.digitization_uncertainty`); there is no shared tool yet.

### 8. Metadata checklist

Fill `RecordMeta` (see `src/iact_perf/schema.py` for the allowed values).
Search the text, the captions and the footnotes for each item:

- `quantity` and `definition`: e.g. angular resolution as 68 % containment
  (`containment_68`) or as the sigma of a Gaussian fit (`gaussian_sigma`);
  energy resolution as Gaussian sigma, RMS or half of the central 68 %
  interval (`containment_68`). Read how the paper computes it.
- `analysis`: see section 5.
- `energy_type`: `true` (MC true energy) or `reconstructed`. They often
  differ within one paper: in the MAGIC example, the energy resolution bins
  are in true energy, the sensitivity bins in estimated energy, and the
  integral threshold is a true-energy peak from MC.
- `data_kind`: `monte_carlo` or `real_data` (e.g. Crab observations).
- `observation_time`: required for sensitivities (`"50 h"`).
- `sensitivity_criteria`: significance, formula (`excess_over_sqrt_background`
  or Li & Ma eq. 17 with its number of OFF regions), minimum excess events,
  minimum signal/background ratio, bins per decade for differential curves.
  Use `"none"` when the paper states there is no such condition, `"unknown"`
  when it does not say.
- `conditions`: zenith range (a single zenith is `[20 deg, 20 deg]`),
  azimuth, offset, Moon, `analysis_details`, cuts.
- `provenance`: `method`, `location` (table or figure number **and** LaTeX
  label, e.g. `"Table A.7 (tab:diffsens)"`), `original_column` (the header as
  printed with its unit, or the curve as the caption describes it).
- `label`: a short sentence a human can read in a list.

### 9. Check

```bash
uv run python sources/<slug>/extract.py   # writes the records
uv run iact-perf validate                 # schema, units, references, slug
uv run iact-perf reproduce <slug>         # re-runs extract.py, compares
uv run pytest                             # whole test suite
uv run ruff format . && uv run ruff check .
```

Validation does not prove the numbers are right. Check them yourself:

- For every record from a table, compare the first, the last and one middle
  row with the paper, every column, including the sign and side of
  asymmetric errors. Check the row count (a dropped first row is a classic).
- When the paper gives the same values in two forms (C.U. and absolute flux),
  convert one into the other with `iact_perf.load().convert(...)`; they must
  agree to the rounding of the published digits. See
  `tests/test_database.py::test_crab_conversion_matches_magic_tables`.
- Compare with every number the text quotes ("an angular resolution of
  0.05 deg at 1 TeV", "a bias below 5 % above 200 GeV"). Expect agreement
  within the rounding of the sentence; report disagreements, do not hide them.
- For figures, see [Figures](#figures).

### 10. Report

End with a short report to the human:

- the records written, grouped by quantity and analysis;
- the values you did not extract, and why;
- points dropped (outside axes) and where;
- every metadata field set to `unknown` that a careful reader might expect
  to be known;
- every judgement call (a definition inferred from a caption, a convention
  you had to interpret, an inconsistency in the paper);
- the checks you ran and their results, including the ones that disagree;
- **any change outside `sources/<slug>/`** (shared code, schema, other
  sources, `pyproject.toml`), with the reason. Fixing a real bug in shared
  code is welcome, but it must be visible.

The human, as the contributor, is responsible for the values. Give them what
they need to check your work quickly.

## Changing the schema

Do not change `src/iact_perf/schema.py` to make a source fit without asking.
If a source needs a new field or value, propose it. After a schema change:
`uv run iact-perf export-schema`, update `docs/design.md`, and bump
`SCHEMA_VERSION` if old files would no longer validate (then update every
`schema_version` and re-run every `extract.py`).

## Commands

| Command | Does |
|---|---|
| `uv run iact-perf validate` | check every database file |
| `uv run iact-perf reproduce [slug ...]` | re-run `extract.py` in a temporary directory and diff with the committed records |
| `uv run iact-perf reproduce <slug> --update` | write the produced records into the source (review with `git diff`) |
| `uv run iact-perf list [--source S] [--quantity Q] [--instrument I] [--analysis A]` | list records |
| `uv run iact-perf new <slug>` | create a source directory from templates |
| `uv run iact-perf export-schema` | regenerate `schema/*.schema.json` |
| `uv run pytest -m network` | the reproduction tests (need internet) |

# Cite a value

Cite the original source of every value you use, then this database. The
source gets the credit for the measurement; the database only made it easy to
find.

## Find the source

```python
import iact_perf

db = iact_perf.load()
rec = db.get(
    "magic_aleksic2016_performance-upgrade",
    "sensitivity_differential_excess-over-sqrt-bkg_crab_zd00-30",
)
src = db.source_of(rec)
print(src.title)
print(", ".join(src.authors), src.year)
print(f"https://doi.org/{src.doi}" if src.doi else f"{src.url} (accessed {src.accessed})")
print(src.arxiv, src.ads_bibcode)
```

A source has a DOI when the publisher gives one. Otherwise it has a URL and
the date it was accessed.

## Say where in the source

`provenance` tells which table or figure the values come from, and how they
were taken:

```python
p = rec.meta.provenance
print(p.method)  # latex_table, pdf_table, vector_figure, raster_digitized, official_data_file
print(p.location)  # e.g. "Table A.7 (tab:diffsens)"
print(p.original_column)  # the column header or curve as printed
```

Values read from a figure (`vector_figure`, `raster_digitized`) are less
precise than values from a table or a data file. A digitised raster figure
states its uncertainty in `p.digitization_uncertainty`.

## Cite the database

The repository has a `CITATION.cff` file with the citation of the database
itself. The data are under CC-BY-4.0, the code under BSD-3-Clause.

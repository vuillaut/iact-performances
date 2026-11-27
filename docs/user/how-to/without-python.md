# Use the data without the library

The records are plain text files. You can read them without `iact_perf`, from
another language, or from a local copy of the repository.

## Read an ECSV file

Each record is an [ECSV](https://github.com/astropy/astropy-APEs/blob/main/APE6.rst)
file: a YAML header in comment lines, then a space-separated table. The header
holds the unit of each column and, under `meta.iact_perf`, the metadata of the
record. Every source page of this website links its record files.

astropy reads them directly:

```python
from pathlib import Path

from astropy.table import QTable

from iact_perf.catalog import default_root

path = (
    default_root()
    / "sources/magic_aleksic2016_performance-upgrade"
    / "sensitivity_differential_excess-over-sqrt-bkg_flux_zd00-30.ecsv"
)
t = QTable.read(path, format="ascii.ecsv")
print(t["value"].unit)
print(t.meta["iact_perf"]["sensitivity_criteria"])
```

Without astropy, skip the lines that start with `#` to get the numbers, and
parse the commented YAML to get the header. A value in Crab units has the
unit `CU %`: it is not a flux, see [Convert Crab units](crab-units.md).

## The JSON export

The website publishes every record in one file, `data/records.json`, used by
the [comparison page](../../compare.md). Values there are **converted** to a
common unit per quantity (E² dN/dE in erg cm⁻² s⁻¹ for differential
sensitivities, for example), and rounded to 6 significant digits. Use the
ECSV files when you need the values as published.

## The JSON Schema

The `schema/` directory of the repository has a JSON Schema for each kind of
file: `record.schema.json` (the `iact_perf` header of a record),
`source.schema.json`, `instrument.schema.json`, `crab_spectra.schema.json`,
`analyses.schema.json`. Use them to validate or to generate types in another
language.

## Work from a local checkout

To use records that are not released yet, or your own additions, point the
library at a clone of the repository:

```bash
git clone https://github.com/vuillaut/iact-performances
export IACT_PERF_ROOT=$PWD/iact-performances
```

`iact_perf.load()` then reads that directory. You can also pass it directly:
`iact_perf.load("path/to/iact-performances")`. The order of precedence is the
`root` argument, then `IACT_PERF_ROOT`, then the checkout the package is
installed from in editable mode, then the data bundled with the package.

To check a modified checkout:

```bash
iact-perf --root path/to/iact-performances validate
```

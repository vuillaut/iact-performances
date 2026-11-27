# Convert Crab units

Many papers give sensitivities as a fraction of the Crab flux, in `% C.U.`.
The database stores them as published, with the unit `% CU`, and names the
Crab spectrum that defines the unit (`crab_reference`). astropy cannot convert
`CU` to a flux on its own: the conversion depends on that spectrum, so it goes
through `db.convert`.

## From Crab units to a flux

```python
import iact_perf

db = iact_perf.load()
rec = db.get(
    "magic_aleksic2016_performance-upgrade",
    "sensitivity_differential_excess-over-sqrt-bkg_crab_zd00-30",
)
print(rec.table["value"].unit, rec.meta.crab_reference)

flux = db.convert(rec, "erg cm-2 s-1")  # E² dN/dE
dnde = db.convert(rec, "cm-2 s-1 TeV-1")  # dN/dE
```

`db.convert` returns a copy of the table with `value` and its errors in the
new unit. The record is not modified.

The conventions are those of most performance papers:

- a differential value is relative to the Crab dN/dE at the energy of the
  point, or at the geometric bin centre when only the bin edges are given;
- an integral value is relative to the integral Crab flux above the threshold
  energy (integrated up to 1000 TeV).

The Crab spectrum itself is in `db.crab_spectra`:

```python
spectrum = db.crab_spectrum(rec)
print(spectrum.model, spectrum.amplitude, spectrum.index, spectrum.reference)
```

## From a flux to Crab units

A record in absolute flux has no `crab_reference`, so you choose the spectrum:

```python
rec = db.query(
    instrument="ctao",
    analysis="prod6-official",
    quantity="sensitivity",
    energy_integration="differential",
    zenith="20 deg",
    observation_time="50 h",
)[0]
in_cu = db.convert(rec, "% CU", crab_reference="magic_aleksic2016")
```

Results in Crab units depend on the spectrum by tens of percent at the ends
of the energy range. Say which one you used.

## Records that refuse to convert

Some sensitivities are computed on Crab observations. Their Crab unit is the
Crab observed in the same data, not a spectral model: the Crab reference has
`model: observed`. Converting these to a flux raises `NoCrabModel`, because
any number would be invented.

```python
from iact_perf.crab import NoCrabModel

rec = db.query(source="lst1_abe2023_crab-performance", quantity="sensitivity")[0]
try:
    db.convert(rec, "erg cm-2 s-1")
except NoCrabModel as err:
    print(err)
```

Compare these records with other values in Crab units, and keep in mind that
each Crab unit is a slightly different flux.

## Lower-level functions

`iact_perf.crab.convert`, `dnde` and `integral_flux` work on plain quantities
and a `CrabSpectrum`, without a record. See the [API reference](../api.md#crab-units).

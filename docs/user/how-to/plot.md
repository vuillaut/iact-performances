# Plot a curve

Records are astropy tables, so plotting is a few lines of matplotlib. Two
details matter: whether the record has bins or points, and which errors it
has.

## One curve with its bins and errors

```python
import astropy.units as u
import matplotlib.pyplot as plt

import iact_perf

db = iact_perf.load()
rec = db.get(
    "magic_aleksic2016_performance-upgrade",
    "sensitivity_differential_excess-over-sqrt-bkg_flux_zd00-30",
)
t = db.convert(rec, "erg cm-2 s-1")

e = rec.energy.to_value(u.TeV)  # geometric bin centre: for plotting only
xerr = None
if "energy_min" in t.colnames:
    xerr = [e - t["energy_min"].to_value(u.TeV), t["energy_max"].to_value(u.TeV) - e]
yerr = None
if "value_err_low" in t.colnames:
    yerr = [t["value_err_low"].value, t["value_err_high"].value]

fig, ax = plt.subplots()
ax.errorbar(e, t["value"].value, xerr=xerr, yerr=yerr, fmt="o", label=rec.meta.label)
ax.set(xscale="log", yscale="log", xlabel="Energy [TeV]", ylabel=f"E² dN/dE [{t['value'].unit}]")
ax.legend(fontsize="small")
```

Some notes on this example:

- `rec.energy` returns the `energy` column when the source gives one, and the
  geometric centre of each bin otherwise. Use the bin edges as the horizontal
  error bar so the reader sees what was published.
- Errors are stored as positive sizes, so they go straight into `yerr`.
  Records without errors have no error columns: test for them.
- Differential sensitivities are published in different units: Crab units,
  dN/dE or E² dN/dE. Convert to one unit before you plot curves together (see
  [Convert Crab units](crab-units.md)). `db.convert` returns a new table and
  leaves the record unchanged.

## Several records on one figure

```python
recs = db.query(
    instrument="ctao",
    analysis="prod6-official",
    quantity="sensitivity",
    energy_integration="differential",
    zenith="20 deg",
    observation_time="50 h",
    where=lambda r: r.meta.conditions.moon == "dark",
)

fig, ax = plt.subplots()
for rec in recs:
    t = db.convert(rec, "erg cm-2 s-1")
    ax.step(rec.energy.to_value(u.TeV), t["value"].value, where="mid", label=rec.meta.label)
ax.set(xscale="log", yscale="log", xlabel="Energy [TeV]", ylabel="E² dN/dE [erg cm⁻² s⁻¹]")
ax.legend(fontsize="small")
```

Before you put curves from different sources on one figure, read
[Compare results fairly](compare.md).

The [comparison page](../../compare.md) of this website does the same
interactively.

# Compare results fairly

Two sensitivity curves on the same axes look comparable. Often they are not.
A sensitivity computed for 50 h with a 5 % signal/background condition, on
Monte Carlo at 20° zenith, can sit far from one computed on Crab data at
0–35° with no such condition, and neither is wrong. Before you compare, check
what differs.

## What changes a curve

| Field | Why it matters |
|---|---|
| `observation_time` | sensitivity scales roughly as 1/√t in the background-limited regime, and faster where the minimum excess dominates |
| `sensitivity_criteria` | the significance formula (`excess_over_sqrt_background` or Li & Ma), the number of OFF regions, the minimum excess, the minimum signal/background ratio and the bins per decade all move the curve |
| `definition` | a 68 % containment radius is larger than the sigma of a Gaussian fit; an energy resolution as an RMS differs from a Gaussian sigma |
| `energy_type` | binned in true or in reconstructed energy |
| `data_kind` | Monte Carlo or real data |
| `conditions.zenith_range` | the threshold rises with zenith |
| `conditions.moon`, `conditions.offset`, `conditions.cuts` | background and acceptance change |
| `crab_reference` | each Crab unit is a different flux |

## Print the differences

This helper shows the fields that differ between records:

```python
import iact_perf

db = iact_perf.load()


def differences(records):
    """Header fields whose value is not the same in every record."""

    def flat(rec):
        d = rec.meta.model_dump(exclude={"label", "provenance", "notes", "schema_version"})
        out = {}
        for key, value in d.items():
            if isinstance(value, dict):
                out |= {f"{key}.{k}": v for k, v in value.items()}
            else:
                out[key] = value
        return out

    rows = [flat(r) for r in records]
    keys = sorted(set().union(*rows))
    return {
        k: [row.get(k) for row in rows] for k in keys if len({str(row.get(k)) for row in rows}) > 1
    }


magic = db.get(
    "magic_aleksic2016_performance-upgrade",
    "sensitivity_differential_excess-over-sqrt-bkg_flux_zd00-30",
)
ctao = db.get("ctao_prod6-v1.0_performance", "sensitivity_differential_north_zd20_dark_50h")

for field, values in differences([magic, ctao]).items():
    print(f"{field:45} {values}")
```

Each line it prints is a reason the two curves may disagree. Some differences
are what you want to compare (the instrument, the analysis), others are not
(the signal/background condition, the energy definition).

## Read the source notes

The header does not hold everything. The notes of a source say which points
were dropped, which errata apply, and which conventions the authors used:

```python
print(db.source_of(magic).notes)
```

## Compare analyses on the same instrument

The `analysis` field separates results of different reconstruction methods on
the same telescopes. To compare methods, fix the configuration and the
definition, then look at what still differs:

```python
recs = db.query(
    instrument="ctao",
    configuration="south_alpha_mst",
    quantity="angular_resolution",
    definition="containment_68",
    zenith="20 deg",
)
for rec in recs:
    m = rec.meta
    print(f"{m.analysis:27} {m.energy_type:14} {m.observation_time or '-':6} {rec.id}")
```

The four reconstruction methods of one paper share an event selection and are
directly comparable. The official Prod5 curves of the same sub-array come in
true and reconstructed energy, with cuts optimised for different observation
times: pick the one that matches before you compare.

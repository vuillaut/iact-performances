"""Export the database to one JSON file for the comparison page.

Each record is converted to the plotting unit of its quantity so that curves of
different sources share an axis: differential sensitivities to E^2 dN/dE in
erg cm-2 s-1 (values in Crab units through the record's Crab spectrum),
integral sensitivities to cm-2 s-1, resolutions to degrees or fractions.
Records whose unit cannot be converted keep their own unit and form their own
group (e.g. a background rate per square degree and one per signal region).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import astropy.units as u

from ..crab import NoCrabModel
from ..database import Database
from ..records import Record
from ..units import CU, is_crab_unit

#: Plotting unit per (quantity, energy integration), then per quantity.
PLOT_UNITS = {
    ("sensitivity", "differential"): "erg cm-2 s-1",
    ("sensitivity", "integral"): "cm-2 s-1",
    "angular_resolution": "deg",
    "energy_resolution": "",
    "energy_bias": "",
    "effective_area": "m2",
}

QUANTITY_NAMES = {
    "sensitivity": "sensitivity",
    "angular_resolution": "Angular resolution",
    "energy_resolution": "Energy resolution",
    "energy_bias": "Energy bias",
    "effective_area": "Effective area",
    "background_rate": "Background rate",
    "gamma_rate": "Gamma-ray rate",
    "energy_threshold": "Energy threshold",
    "field_of_view": "Field of view",
}

#: Quantities plotted on a linear y axis (can be negative).
LINEAR_Y = {"energy_bias"}


def _sig(x, digits: int = 6):
    if x is None or not math.isfinite(x):
        return None
    return float(f"{x:.{digits}g}")


def _unit_label(unit: u.UnitBase) -> str:
    if unit == u.dimensionless_unscaled:
        return ""
    return unit.to_string("unicode")


def group_of(rec: Record) -> tuple[str, str, u.UnitBase]:
    """(group key, human name, plotting unit) of a record."""
    m = rec.meta
    native = rec.table["value"].unit or u.dimensionless_unscaled
    target = PLOT_UNITS.get((m.quantity, m.energy_integration), PLOT_UNITS.get(m.quantity))
    unit = u.Unit(target) if target is not None else native.decompose().si
    if target is None:
        # keep the native unit family, expressed in a readable unit
        for readable in ("s-1 deg-2", "s-1", "min-1", "s-1 TeV-1"):
            if native.is_equivalent(readable):
                unit = u.Unit(readable)
                break
    name = QUANTITY_NAMES[m.quantity]
    if m.quantity == "sensitivity":
        name = f"{m.energy_integration.capitalize()} sensitivity"
        if m.energy_integration == "differential":
            name += " (E² dN/dE)"
    elif m.energy_integration:
        name = f"{name} ({m.energy_integration})"
    label = _unit_label(unit)
    key = f"{m.quantity}|{m.energy_integration or ''}|{unit.to_string()}"
    return key, f"{name} [{label}]" if label else name, unit


def _entry(db: Database, rec: Record, table, key: str, unit: u.UnitBase, uid: str) -> dict:
    m = rec.meta
    energy = rec.energy.to_value(u.TeV)
    cols = table.colnames
    points = {
        "x": [_sig(float(v)) for v in energy],
        "y": [_sig(float(v)) for v in table["value"].to_value(unit)],
    }
    if "energy_min" in cols:
        points["xlo"] = [_sig(float(v)) for v in table["energy_min"].to_value(u.TeV)]
        points["xhi"] = [_sig(float(v)) for v in table["energy_max"].to_value(u.TeV)]
    for name_, short in (("value_err_low", "ylo"), ("value_err_high", "yhi")):
        if name_ in cols:
            points[short] = [_sig(float(v)) for v in table[name_].to_value(unit)]

    zr = m.conditions.zenith_range
    native = rec.table["value"].unit or u.dimensionless_unscaled
    converted = None
    if native == unit:
        pass
    elif is_crab_unit(native) and not is_crab_unit(unit):
        converted = f"converted from {native.to_string()} with Crab spectrum {m.crab_reference}"
    else:
        converted = f"converted from {native.to_string()}"
    crab = db.crab_spectra.get(m.crab_reference) if m.crab_reference else None
    return {
        "uid": uid,
        "group": key,
        "source": rec.source,
        "label": m.label.replace("<", "‹"),
        "quantity": m.quantity,
        "definition": m.definition,
        "integration": m.energy_integration,
        "energy_type": m.energy_type,
        "instrument": m.instrument,
        "configuration": m.configuration,
        "analysis": m.analysis,
        "data_kind": m.data_kind,
        "zenith": None if zr == "unknown" else [u.Quantity(z).to_value(u.deg) for z in zr],
        "obs_time_h": None
        if m.observation_time is None
        else _sig(u.Quantity(m.observation_time).to_value(u.h)),
        "obs_time": m.observation_time,
        "moon": m.conditions.moon,
        "offset": m.conditions.offset,
        "provenance": f"{m.provenance.method}: {m.provenance.location}",
        "converted": converted,
        "crab": None if crab is None else f"Crab unit: {crab.id} ({crab.model})",
        "min_s2b": None
        if m.sensitivity_criteria is None
        else m.sensitivity_criteria.min_signal_to_background,
        "superseded": db.is_superseded(rec),
        **points,
    }


def _crab_group(rec: Record) -> tuple[str, str, u.UnitBase]:
    """Group of the values in Crab units: curves published in C.U. compare there."""
    m = rec.meta
    unit = u.percent * CU
    name = f"{m.energy_integration.capitalize()} sensitivity [% C.U.]"
    return f"{m.quantity}|{m.energy_integration}|% CU", name, unit


def export(db: Database, path: Path) -> dict:
    """Write ``records.json`` and return a summary (records exported and skipped).

    A record published in Crab units appears twice when its Crab spectrum is
    a model: converted to the flux group, and as published in the % C.U.
    group. With an observed Crab reference it only appears in the % C.U. group.
    """
    groups: dict[str, dict] = {}
    records, skipped = [], []
    for rec in db.records:
        native = rec.table["value"].unit or u.dimensionless_unscaled
        targets = [group_of(rec)]
        if rec.meta.quantity == "sensitivity" and is_crab_unit(native):
            targets.append(_crab_group(rec))
        exported = 0
        for key, name, unit in targets:
            try:
                table = db.convert(rec, unit)
            except NoCrabModel:
                continue  # stays in its % C.U. group only
            except (u.UnitConversionError, ValueError) as err:
                skipped.append(f"{rec.source}/{rec.id}: {err}")
                continue
            # the first entry of a record keeps its plain id; a second one is "@cu"
            uid = f"{rec.source}/{rec.id}" + ("@cu" if exported else "")
            records.append(_entry(db, rec, table, key, unit, uid))
            groups.setdefault(
                key,
                {"key": key, "name": name, "log_y": rec.meta.quantity not in LINEAR_Y, "n": 0},
            )
            groups[key]["n"] += 1
            exported += 1
        if not exported and not any(s.startswith(f"{rec.source}/{rec.id}:") for s in skipped):
            skipped.append(f"{rec.source}/{rec.id}: no group")

    sources = {
        slug: {
            "title": s.title,
            "authors": s.authors,
            "year": s.year,
            "doi": s.doi,
            "url": s.url,
            "type": s.source_type,
            "refereed": s.refereed,
        }
        for slug, s in db.sources.items()
    }
    configurations = {
        f"{inst.id}/{c.id}": c.description
        for inst in db.instruments.values()
        for c in inst.configurations
    }
    data = {
        "groups": sorted(groups.values(), key=lambda g: g["name"]),
        "records": records,
        "sources": sources,
        "instruments": {i.id: i.name for i in db.instruments.values()},
        "configurations": configurations,
        "analyses": {a.id: a.name for a in db.analyses.values()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    return {"records": len(records), "skipped": skipped, "groups": len(groups)}

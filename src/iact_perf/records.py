"""Reading, writing and checking record files (ECSV)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.table import QTable, Table

from .schema import SCALAR_QUANTITIES, VALUE_UNITS, RecordMeta
from .units import is_crab_unit

META_KEY = "iact_perf"

ENERGY_COLUMNS = ("energy", "energy_min", "energy_max")
VALUE_COLUMNS = ("value", "value_err_low", "value_err_high")
COLUMNS = ENERGY_COLUMNS + VALUE_COLUMNS


@dataclass
class Record:
    """One record: its table (with units) and its validated header."""

    table: QTable
    meta: RecordMeta
    path: Path | None = None

    @property
    def id(self) -> str:
        return self.path.stem if self.path else ""

    @property
    def source(self) -> str | None:
        """Slug of the source the record belongs to (its directory name)."""
        return self.path.parent.name if self.path else None

    @property
    def energy(self) -> u.Quantity | None:
        """Energy of each point: the ``energy`` column, else the geometric bin centre."""
        t = self.table
        if "energy" in t.colnames:
            return t["energy"]
        if "energy_min" in t.colnames:
            return np.sqrt(t["energy_min"] * t["energy_max"])
        return None

    def __repr__(self) -> str:
        return f"<Record {self.source}/{self.id}: {self.meta.label}>"


def write_record(path: Path, columns: dict[str, u.Quantity], meta: RecordMeta) -> Path:
    """Check ``columns`` against ``meta`` and write them as an ECSV record.

    ``columns`` maps canonical column names to quantities. The values are
    written as they are: pass the numbers as published, in the published unit.
    """
    table = Table()
    for name in COLUMNS:
        if name in columns:
            q = u.Quantity(columns[name])
            table[name] = q.value
            table[name].unit = q.unit
    unknown = set(columns) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown columns {sorted(unknown)}, allowed: {COLUMNS}")
    table.meta[META_KEY] = meta.model_dump(mode="json", exclude_none=True)

    errors = check_columns(QTable(table), meta)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.write(path, format="ascii.ecsv", overwrite=True)
    return path


def read_record(path: Path) -> Record:
    """Read an ECSV record. Raises ``ValueError`` if its header is not valid."""
    table = QTable.read(path, format="ascii.ecsv")
    raw = table.meta.get(META_KEY)
    if raw is None:
        raise ValueError(f"{path}: no '{META_KEY}' metadata in the ECSV header")
    meta = RecordMeta.model_validate(raw)
    return Record(table=table, meta=meta, path=Path(path))


def check_columns(table: QTable, meta: RecordMeta) -> list[str]:
    """Return the problems found in the columns of a record (empty if none)."""
    errors = []
    names = set(table.colnames)

    extra = names - set(COLUMNS)
    if extra:
        errors.append(f"unknown columns {sorted(extra)}")
    if "value" not in names:
        return errors + ["missing column 'value'"]
    if len(table) == 0:
        errors.append("empty table")

    value_unit = _unit(table["value"])
    allowed = VALUE_UNITS[meta.quantity]
    if not any(value_unit.is_equivalent(a) for a in allowed):
        errors.append(
            f"unit {value_unit!r} of 'value' not valid for {meta.quantity}: "
            f"expected one of {[str(a) for a in allowed]}"
        )
    if is_crab_unit(value_unit) and meta.crab_reference is None:
        errors.append("values in Crab units need 'crab_reference'")

    for name in ("value_err_low", "value_err_high"):
        if name in names:
            if not _unit(table[name]).is_equivalent(value_unit):
                errors.append(f"unit of {name!r} differs from the unit of 'value'")
            elif np.any(_values(table[name]) < 0):
                errors.append(f"{name!r} must be positive (an error size, not a signed offset)")

    has_bins = "energy_min" in names and "energy_max" in names
    if meta.quantity not in SCALAR_QUANTITIES and "energy" not in names and not has_bins:
        errors.append(
            f"{meta.quantity} is a curve versus energy: it needs 'energy' "
            "or 'energy_min' and 'energy_max'"
        )
    for name in ENERGY_COLUMNS:
        if name in names and not _unit(table[name]).is_equivalent(u.TeV):
            errors.append(f"column {name!r} is not an energy")
    if ("energy_min" in names) != ("energy_max" in names):
        errors.append("'energy_min' and 'energy_max' go together")
    elif "energy_min" in names and not errors:
        lo = table["energy_min"].to_value(u.TeV)
        hi = table["energy_max"].to_value(u.TeV)
        if np.any(lo >= hi):
            errors.append("'energy_min' must be below 'energy_max'")
        if "energy" in names:
            e = table["energy"].to_value(u.TeV)
            if np.any((e < lo) | (e > hi)):
                errors.append("'energy' outside [energy_min, energy_max]")
    return errors


def _unit(column) -> u.UnitBase:
    return getattr(column, "unit", None) or u.dimensionless_unscaled


def _values(column) -> np.ndarray:
    return np.asarray(getattr(column, "value", column), dtype=float)

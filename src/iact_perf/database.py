"""Querying the database.

>>> import iact_perf
>>> db = iact_perf.load()
>>> recs = db.query(quantity="sensitivity", instrument="magic",
...                 energy_integration="differential", zenith="20 deg")
>>> table = db.convert(recs[0], "erg cm-2 s-1")
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.table import QTable, Table

from . import crab
from .catalog import (
    default_root,
    load_analyses,
    load_crab_spectra,
    load_instruments,
    load_source,
    source_dirs,
)
from .records import Record
from .schema import Analysis, CrabSpectrum, Instrument, Source

# Record header fields that can be filtered by equality in Database.query
META_FILTERS = (
    "quantity",
    "definition",
    "energy_integration",
    "energy_type",
    "instrument",
    "configuration",
    "analysis",
    "data_kind",
    "crab_reference",
)


@dataclass
class Database:
    """The whole database in memory. Get it with :func:`iact_perf.load`.

    The attributes map identifiers to objects: ``instruments["magic"]``,
    ``sources["magic_aleksic2016_performance-upgrade"]``,
    ``crab_spectra["magic_aleksic2016"]``, ``analyses["prod6-official"]``.
    ``records`` lists every record, superseded ones included.
    """

    instruments: dict[str, Instrument]
    sources: dict[str, Source]
    records: list[Record]
    crab_spectra: dict[str, CrabSpectrum]
    analyses: dict[str, Analysis]

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return (
            f"<Database: {len(self.records)} records from {len(self.sources)} sources, "
            f"{len(self.instruments)} instruments>"
        )

    def source_of(self, record: Record) -> Source:
        """The publication a record comes from: title, authors, DOI, notes."""
        return self.sources[record.source]

    def is_superseded(self, record: Record) -> bool:
        """True if a newer source replaces the source of this record."""
        return self.source_of(record).superseded_by is not None

    def query(
        self,
        *,
        source: str | None = None,
        zenith: u.Quantity | str | None = None,
        observation_time: u.Quantity | str | None = None,
        include_superseded: bool = False,
        where: Callable[[Record], bool] | None = None,
        **filters,
    ) -> list[Record]:
        """Records matching all the given criteria.

        Keyword filters compare record header fields by equality (a list or
        tuple means "any of"): ``quantity``, ``definition``,
        ``energy_integration``, ``energy_type``, ``instrument``,
        ``configuration``, ``analysis``, ``data_kind``, ``crab_reference``.

        ``zenith`` keeps records whose zenith range contains this angle;
        records with an unknown zenith range are dropped. ``observation_time``
        keeps records with this observation time. Records of superseded
        sources are left out unless ``include_superseded`` is true. ``where``
        is any extra predicate on the record.
        """
        unknown = set(filters) - set(META_FILTERS)
        if unknown:
            raise TypeError(f"unknown filters {sorted(unknown)}, allowed: {META_FILTERS}")

        out = []
        for rec in self.records:
            m = rec.meta
            if not include_superseded and self.is_superseded(rec):
                continue
            if source is not None and rec.source != source:
                continue
            if any(not _match(getattr(m, k), v) for k, v in filters.items()):
                continue
            if zenith is not None and not _zenith_contains(m.conditions.zenith_range, zenith):
                continue
            if observation_time is not None and (
                m.observation_time is None
                or not u.isclose(u.Quantity(m.observation_time), u.Quantity(observation_time))
            ):
                continue
            if where is not None and not where(rec):
                continue
            out.append(rec)
        return out

    def get(self, source: str, record_id: str) -> Record:
        """The record ``record_id`` (its file name without ``.ecsv``) of ``source``.

        Raises ``KeyError`` if there is none.
        """
        for rec in self.records:
            if rec.source == source and rec.id == record_id:
                return rec
        raise KeyError(f"no record {source}/{record_id}")

    def crab_spectrum(self, record: Record) -> CrabSpectrum | None:
        """The Crab spectrum that defines the Crab unit of a record, or None."""
        ref = record.meta.crab_reference
        return self.crab_spectra[ref] if ref else None

    def convert(
        self, record: Record, unit: u.UnitBase | str, crab_reference: str | None = None
    ) -> QTable:
        """Copy of the record table with ``value`` and its errors in ``unit``.

        For sensitivities, converts between Crab units, fluxes and energy
        fluxes (see :mod:`iact_perf.crab`). The Crab spectrum is the record's
        ``crab_reference``, or ``crab_reference`` given here (needed to
        express an absolute flux in CU). Other quantities convert with
        astropy only.

        Raises :class:`iact_perf.crab.NoCrabModel` when the record's Crab
        unit is the observed Crab (``model: observed``): such values have no
        absolute flux. The record itself is never modified.
        """
        table = QTable(record.table, copy=True)
        unit = u.Unit(unit)
        value = table["value"]
        if record.meta.quantity == "sensitivity":
            ref = crab_reference or record.meta.crab_reference
            spectrum = self.crab_spectra[ref] if ref else None
            args = (unit, record.energy, record.meta.energy_integration, spectrum)
            converted = crab.convert(value, *args)
            factor = crab.convert(np.ones(len(value)) * value.unit, *args)
        else:
            converted = value.to(unit)
            factor = (1 * value.unit).to(unit) * np.ones(len(value))
        table["value"] = converted
        for name in ("value_err_low", "value_err_high"):
            if name in table.colnames:
                table[name] = table[name].to_value(value.unit) * factor
        return table

    def summary(self, records: list[Record] | None = None) -> Table:
        """One row per record, to browse the database."""
        rows = []
        for rec in self.records if records is None else records:
            m = rec.meta
            zr = m.conditions.zenith_range
            rows.append(
                {
                    "source": rec.source,
                    "record": rec.id,
                    "quantity": m.quantity,
                    "definition": m.definition or "",
                    "integration": m.energy_integration or "",
                    "instrument": m.instrument,
                    "configuration": m.configuration,
                    "analysis": m.analysis,
                    "data_kind": m.data_kind,
                    "zenith": zr if isinstance(zr, str) else "-".join(zr),
                    "obs_time": m.observation_time or "",
                    "unit": str(rec.table["value"].unit or ""),
                    "n": len(rec.table),
                    "superseded": self.is_superseded(rec),
                }
            )
        names = list(rows[0]) if rows else ["source", "record"]
        return Table(rows=rows, names=names) if rows else Table(names=names)


def load(root: Path | str | None = None) -> Database:
    """Load the whole database from ``root`` (default: the bundled data)."""
    root = Path(root) if root else default_root()
    sources, records = {}, []
    for path in source_dirs(root):
        entry = load_source(path)
        sources[entry.slug] = entry.source
        records += entry.records
    return Database(
        instruments=load_instruments(root),
        sources=sources,
        records=records,
        crab_spectra={s.id: s for s in load_crab_spectra(root).spectra},
        analyses={a.id: a for a in load_analyses(root).analyses},
    )


def _match(actual, wanted) -> bool:
    if isinstance(wanted, list | tuple | set):
        return actual in wanted
    return actual == wanted


def _zenith_contains(zenith_range, zenith) -> bool:
    if zenith_range == "unknown":
        return False
    lo, hi = (u.Quantity(z).to_value(u.deg) for z in zenith_range)
    return lo <= u.Quantity(zenith).to_value(u.deg) <= hi

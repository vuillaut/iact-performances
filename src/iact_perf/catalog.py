"""Loading the database files from a checkout of the repository, and validating them."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .records import Record, check_columns, read_record
from .schema import SCHEMA_VERSION, SLUG_RE, Analyses, CrabSpectra, Instrument, Source

#: Files that must never be committed in a source directory (copyright, size).
FORBIDDEN_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".eps", ".ps", ".svg",
    ".tar", ".gz", ".tgz", ".zip", ".fits", ".root",
}  # fmt: skip


def default_root() -> Path:
    """Where the database files are.

    In order: the ``IACT_PERF_ROOT`` environment variable, the repository
    checkout this package lives in (editable install), the data bundled in
    the wheel.
    """
    env = os.environ.get("IACT_PERF_ROOT")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    if (repo / "sources").is_dir():
        return repo
    return Path(__file__).resolve().parent / "data"


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


@dataclass
class SourceEntry:
    slug: str
    path: Path
    source: Source
    records: list[Record] = field(default_factory=list)


def load_instruments(root: Path) -> dict[str, Instrument]:
    return {
        p.stem: Instrument.model_validate(_load_yaml(p))
        for p in sorted((root / "instruments").glob("*.yaml"))
    }


def load_crab_spectra(root: Path) -> CrabSpectra:
    return CrabSpectra.model_validate(_load_yaml(root / "references" / "crab_spectra.yaml"))


def load_analyses(root: Path) -> Analyses:
    return Analyses.model_validate(_load_yaml(root / "references" / "analyses.yaml"))


def load_source(path: Path) -> SourceEntry:
    source = Source.model_validate(_load_yaml(path / "source.yaml"))
    records = [read_record(p) for p in sorted(path.glob("*.ecsv"))]
    return SourceEntry(slug=path.name, path=path, source=source, records=records)


def source_dirs(root: Path) -> list[Path]:
    return sorted(p for p in (root / "sources").iterdir() if p.is_dir())


def validate_repository(root: Path | None = None) -> list[str]:
    """Check every file of the database. Returns the list of problems (empty if valid)."""
    root = Path(root) if root else default_root()
    errors: list[str] = []

    instruments: dict[str, Instrument] = {}
    for p in sorted((root / "instruments").glob("*.yaml")):
        try:
            inst = Instrument.model_validate(_load_yaml(p))
        except ValidationError as err:
            errors.append(f"{p.relative_to(root)}: {err}")
            continue
        if inst.id != p.stem:
            errors.append(f"{p.relative_to(root)}: id {inst.id!r} differs from file name")
        errors += _check_version(p.relative_to(root), inst.schema_version)
        instruments[inst.id] = inst

    refs = {}
    for name, loader, attr in (
        ("crab_spectra", load_crab_spectra, "spectra"),
        ("analyses", load_analyses, "analyses"),
    ):
        try:
            registry = loader(root)
        except (OSError, ValidationError) as err:
            errors.append(f"references/{name}.yaml: {err}")
            refs[name] = set()
            continue
        errors += _check_version(f"references/{name}.yaml", registry.schema_version)
        refs[name] = {item.id for item in getattr(registry, attr)}

    dirs = source_dirs(root)
    slugs = {p.name for p in dirs}
    for path in dirs:
        errors += _validate_source(root, path, slugs, instruments, refs)
    return errors


def _check_version(where, version) -> list[str]:
    if version != SCHEMA_VERSION:
        return [f"{where}: schema_version {version!r}, expected {SCHEMA_VERSION!r}"]
    return []


def _validate_source(root, path, slugs, instruments, refs) -> list[str]:
    rel = path.relative_to(root)
    errors = []
    if not SLUG_RE.match(path.name):
        errors.append(f"{rel}: directory name is not a valid slug")

    for f in path.rglob("*"):
        if f.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"{f.relative_to(root)}: {f.suffix} files must not be committed")

    try:
        source = Source.model_validate(_load_yaml(path / "source.yaml"))
    except (OSError, ValidationError) as err:
        return errors + [f"{rel}/source.yaml: {err}"]

    errors += _check_version(f"{rel}/source.yaml", source.schema_version)
    first = path.name.split("_")[0]
    if first not in source.instruments:
        errors.append(f"{rel}: slug starts with {first!r}, not one of {source.instruments}")
    for inst in source.instruments:
        if inst not in instruments:
            errors.append(f"{rel}/source.yaml: unknown instrument {inst!r}")
    if source.superseded_by and source.superseded_by not in slugs:
        errors.append(f"{rel}/source.yaml: superseded_by {source.superseded_by!r} does not exist")
    if source.reproducible and not (path / "extract.py").exists():
        errors.append(f"{rel}: reproducible is true but there is no extract.py")

    ecsv = sorted(path.glob("*.ecsv"))
    if not ecsv:
        errors.append(f"{rel}: no record (*.ecsv)")
    for p in ecsv:
        prel = p.relative_to(root)
        try:
            rec = read_record(p)
        except (ValueError, ValidationError) as err:
            errors.append(f"{prel}: {err}")
            continue
        errors += [f"{prel}: {e}" for e in check_columns(rec.table, rec.meta)]
        m = rec.meta
        errors += _check_version(prel, m.schema_version)
        if m.analysis not in refs["analyses"]:
            errors.append(f"{prel}: unknown analysis {m.analysis!r} (references/analyses.yaml)")
        if m.instrument not in source.instruments:
            errors.append(f"{prel}: instrument {m.instrument!r} not listed in source.yaml")
        inst = instruments.get(m.instrument)
        if inst and inst.configuration(m.configuration) is None:
            errors.append(f"{prel}: {m.instrument} has no configuration {m.configuration!r}")
        if m.crab_reference and m.crab_reference not in refs["crab_spectra"]:
            errors.append(f"{prel}: unknown crab_reference {m.crab_reference!r}")
    return errors

"""Re-run the extraction script of a source and compare with the committed records.

Contract of ``sources/<slug>/extract.py``: it defines

    def extract(out: Path, cache_dir: Path | None = None) -> None

which downloads what it needs into ``cache_dir`` (never into the repository
tree outside ``.cache/``) and writes every record of the source into ``out``.
"""

from __future__ import annotations

import filecmp
import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .catalog import default_root
from .records import read_record


@dataclass
class Comparison:
    slug: str
    missing: list[str] = field(default_factory=list)  # committed, not produced
    extra: list[str] = field(default_factory=list)  # produced, not committed
    changed: dict[str, str] = field(default_factory=dict)  # name -> what differs

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or self.changed)

    def report(self) -> str:
        if self.ok:
            return f"{self.slug}: OK"
        lines = [f"{self.slug}: DIFFERS"]
        lines += [f"  missing (committed, not produced): {n}" for n in self.missing]
        lines += [f"  extra (produced, not committed):   {n}" for n in self.extra]
        lines += [f"  changed: {n}: {why}" for n, why in self.changed.items()]
        return "\n".join(lines)


def load_extract(source_dir: Path):
    """Import ``extract.py`` of a source and return its ``extract`` function."""
    path = Path(source_dir) / "extract.py"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    name = f"iact_perf_extract_{path.parent.name}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # register before exec: dataclasses and other introspection need the
    # module to be importable while it is being defined
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "extract"):
        raise AttributeError(f"{path} defines no extract(out, cache_dir) function")
    return module.extract


def run_extract(source_dir: Path, out: Path, cache_dir: Path | None = None) -> None:
    load_extract(source_dir)(out=Path(out), cache_dir=cache_dir)


def compare(slug: str, committed_dir: Path, produced_dir: Path) -> Comparison:
    committed = {p.name for p in Path(committed_dir).glob("*.ecsv")}
    produced = {p.name for p in Path(produced_dir).glob("*.ecsv")}
    result = Comparison(slug, sorted(committed - produced), sorted(produced - committed))
    for name in sorted(committed & produced):
        a, b = Path(committed_dir) / name, Path(produced_dir) / name
        if filecmp.cmp(a, b, shallow=False):
            continue
        result.changed[name] = _describe_difference(a, b)
    return result


def _describe_difference(a: Path, b: Path) -> str:
    try:
        ra, rb = read_record(a), read_record(b)
    except Exception as err:  # an invalid produced file is itself the difference
        return f"cannot read: {err}"
    diffs = []
    if ra.meta != rb.meta:
        da, db = ra.meta.model_dump(), rb.meta.model_dump()
        keys = sorted(k for k in da.keys() | db.keys() if da.get(k) != db.get(k))
        diffs.append(f"header fields {keys}")
    if ra.table.colnames != rb.table.colnames:
        diffs.append(f"columns {ra.table.colnames} -> {rb.table.colnames}")
    elif len(ra.table) != len(rb.table):
        diffs.append(f"{len(ra.table)} -> {len(rb.table)} rows")
    else:
        for col in ra.table.colnames:
            ca, cb = ra.table[col], rb.table[col]
            if ca.unit != cb.unit:
                diffs.append(f"unit of {col}: {ca.unit} -> {cb.unit}")
            elif not np.array_equal(ca.value, cb.value, equal_nan=True):
                diffs.append(f"values of {col}")
    return ", ".join(diffs) or "formatting only"


def reproduce(
    slug: str,
    root: Path | None = None,
    cache_dir: Path | None = None,
    update: bool = False,
) -> Comparison:
    """Run the extraction of ``slug`` in a temporary directory and compare.

    With ``update``, the produced records replace the committed ones
    (records no longer produced are not deleted: nothing is ever removed
    without a human decision).
    """
    root = Path(root) if root else default_root()
    source_dir = root / "sources" / slug
    if not source_dir.is_dir():
        raise FileNotFoundError(f"no source {slug!r} in {root / 'sources'}")
    cache_dir = Path(cache_dir) if cache_dir else root / ".cache"
    with tempfile.TemporaryDirectory(prefix=f"iact-perf-{slug}-") as tmp:
        run_extract(source_dir, Path(tmp), cache_dir)
        result = compare(slug, source_dir, Path(tmp))
        if update:
            for name in result.extra + list(result.changed):
                shutil.copy2(Path(tmp) / name, source_dir / name)
    return result

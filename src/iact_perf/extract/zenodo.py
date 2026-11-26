"""Download files of a Zenodo record into the cache, and read archives in memory.

A Zenodo bundle is often a zip of tarballs. :func:`iter_archive` walks it and
yields the bytes of the files you select, without unpacking anything to disk.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

USER_AGENT = "iact-perf"
API = "https://zenodo.org/api/records/{record}"


def default_cache() -> Path:
    from ..catalog import default_root

    return default_root() / ".cache"


def file_info(record: int | str, filename: str) -> tuple[str, str | None]:
    """Download URL and checksum (``md5:...``) of a file of a Zenodo record."""
    import requests

    resp = requests.get(API.format(record=record), headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    for f in resp.json()["files"]:
        if f["key"] == filename:
            return f["links"]["self"], f.get("checksum")
    names = [f["key"] for f in resp.json()["files"]]
    raise FileNotFoundError(f"{filename} not in Zenodo record {record}: {names}")


def md5(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def download(record: int | str, filename: str, cache_dir: Path | None = None) -> Path:
    """Path of ``filename`` from Zenodo ``record`` in the cache, downloaded once.

    The md5 checksum published by Zenodo is checked after the download.
    """
    import requests

    cache_dir = Path(cache_dir) if cache_dir else default_cache()
    path = cache_dir / "zenodo" / str(record) / filename
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url, checksum = file_info(record, filename)
    part = path.with_name(path.name + ".part")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        with open(part, "wb") as out:
            for block in resp.iter_content(1 << 20):
                out.write(block)
    if checksum and checksum.startswith("md5:") and md5(part) != checksum[4:]:
        part.unlink()
        raise OSError(f"checksum mismatch for {filename} of Zenodo record {record}")
    part.rename(path)
    return path


def verify(path: Path, record: int | str) -> None:
    """Check a cached file against the md5 checksum Zenodo publishes for it."""
    _, checksum = file_info(record, Path(path).name)
    if checksum and checksum.startswith("md5:") and md5(path) != checksum[4:]:
        raise OSError(f"{path}: md5 differs from Zenodo record {record}")


def iter_archive(path: Path, select: Callable[[str], bool]) -> Iterator[tuple[str, bytes]]:
    """Yield ``(member path, bytes)`` of the files of a zip or tarball for which
    ``select(basename)`` is true. Tarballs nested in a zip are walked too.

    Nothing is written to disk; member paths are only used as names.
    """
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = Path(info.filename).name
                if base.endswith((".tar.gz", ".tgz", ".tar")):
                    with zf.open(info) as raw:
                        yield from _iter_tar(raw, select, prefix=info.filename + "/")
                elif select(base):
                    yield info.filename, zf.read(info)
    else:
        with open(path, "rb") as raw:
            yield from _iter_tar(raw, select)


def _iter_tar(fileobj: io.IOBase, select, prefix: str = "") -> Iterator[tuple[str, bytes]]:
    with tarfile.open(fileobj=fileobj, mode="r|*") as tf:
        for member in tf:
            if member.isfile() and select(Path(member.name).name):
                f = tf.extractfile(member)
                if f is not None:
                    yield prefix + member.name, f.read()

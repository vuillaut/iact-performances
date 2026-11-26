"""Download the LaTeX source of an arXiv paper into a local cache.

The tarball is never unpacked to disk: the ``.tex`` files are read from it in
memory, so nothing from the archive can land outside the cache.
"""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

USER_AGENT = "iact-perf"


def default_cache() -> Path:
    from ..catalog import default_root

    return default_root() / ".cache"


def download_source(arxiv_id: str, cache_dir: Path | None = None) -> Path:
    """Download the e-print of ``arxiv_id`` (once) and return the cached file path."""
    import requests

    cache_dir = Path(cache_dir) if cache_dir else default_cache()
    path = cache_dir / "arxiv" / f"{arxiv_id.replace('/', '_')}.eprint"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(
        f"https://export.arxiv.org/e-print/{arxiv_id}",
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return path


def read_tex_files(eprint: Path) -> dict[str, str]:
    """Return ``{name: content}`` for every ``.tex`` file of a downloaded e-print.

    An e-print is either a gzipped tarball or a single gzipped ``.tex`` file.
    """
    data = Path(eprint).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data))  # noqa: SIM115 (closed below)
    except tarfile.ReadError:
        return {"main.tex": data.decode("utf-8", errors="replace")}
    out = {}
    with tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith(".tex"):
                f = tar.extractfile(member)
                if f is not None:
                    out[member.name] = f.read().decode("utf-8", errors="replace")
    return out


def read_file(arxiv_id: str, name: str, cache_dir: Path | None = None) -> bytes:
    """Bytes of one file (a figure, a data file) of an arXiv e-print, read in memory."""
    data = Path(download_source(arxiv_id, cache_dir)).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        try:
            member = tar.getmember(name)
        except KeyError:
            raise KeyError(f"{name} not in the arXiv source of {arxiv_id}") from None
        f = tar.extractfile(member) if member.isfile() else None
        if f is None:
            raise KeyError(f"{name} is not a regular file in the arXiv source of {arxiv_id}")
        return f.read()


def list_files(arxiv_id: str, cache_dir: Path | None = None) -> list[str]:
    """Names of the files of an arXiv e-print, to explore it without unpacking."""
    data = Path(download_source(arxiv_id, cache_dir)).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            return sorted(m.name for m in tar.getmembers() if m.isfile())
    except tarfile.ReadError:
        return ["main.tex"]


def get_tex(arxiv_id: str, name: str | None = None, cache_dir: Path | None = None) -> str:
    """LaTeX of an arXiv paper: the file ``name``, or all ``.tex`` files joined."""
    files = read_tex_files(download_source(arxiv_id, cache_dir))
    if name is not None:
        return files[name]
    return "\n".join(files[k] for k in sorted(files))

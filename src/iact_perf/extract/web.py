"""Download a file from a plain URL into the cache, pinned by its md5 checksum.

For sources without an arXiv or Zenodo copy (e.g. a PoS proceedings PDF). The
checksum is the one of the file the extraction was written for: if the
publisher replaces the file, the download fails instead of silently giving
other numbers.
"""

from __future__ import annotations

from pathlib import Path

from .zenodo import USER_AGENT, default_cache, md5


def download(url: str, name: str, md5sum: str, cache_dir: Path | None = None) -> Path:
    """Path of the file at ``url`` in the cache (``<cache>/web/<name>``), downloaded once.

    The md5 checksum is checked after the download and on every later call.
    """
    cache_dir = Path(cache_dir) if cache_dir else default_cache()
    path = cache_dir / "web" / name
    if not path.exists():
        import requests

        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120) as resp:
            resp.raise_for_status()
            part.write_bytes(resp.content)
        part.rename(path)
    if md5(path) != md5sum:
        raise OSError(
            f"{path}: md5 {md5(path)} differs from {md5sum}, the file {url} was written for; "
            "check whether the publisher changed it"
        )
    return path

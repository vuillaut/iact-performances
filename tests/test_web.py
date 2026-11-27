"""The plain-URL download helper, on a pre-filled cache (no network)."""

import hashlib

import pytest

from iact_perf.extract.web import download


def test_cached_file_is_checked(tmp_path):
    path = tmp_path / "web" / "paper.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.5 content")
    good = hashlib.md5(b"%PDF-1.5 content").hexdigest()
    assert download("https://example.org/x", "paper.pdf", good, tmp_path) == path
    with pytest.raises(OSError, match="differs"):
        download("https://example.org/x", "paper.pdf", "0" * 32, tmp_path)

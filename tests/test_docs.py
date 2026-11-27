"""The user guide: its examples run, and the API reference covers the public API."""

import re
from pathlib import Path

import pytest

import iact_perf
from iact_perf.site.apidoc import SECTIONS, api_reference
from iact_perf.site.build import USER_GUIDE

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "user"
BLOCK = re.compile(r"^```python\n(.*?)^```", re.S | re.M)


def test_guide_pages_exist():
    for _, page in USER_GUIDE:
        assert (GUIDE / page).exists(), page
    on_disk = {p.relative_to(GUIDE).as_posix() for p in GUIDE.rglob("*.md")}
    assert on_disk == {p for _, p in USER_GUIDE}, "a page is missing from USER_GUIDE"


@pytest.mark.parametrize("page", [p for _, p in USER_GUIDE])
def test_guide_examples_run(page, monkeypatch, tmp_path):
    """Run the Python blocks of a page in order, in one namespace."""
    pytest.importorskip("matplotlib")
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.chdir(tmp_path)
    blocks = BLOCK.findall((GUIDE / page).read_text())
    assert blocks, f"{page} has no Python example"  # a test that runs nothing must fail
    namespace: dict = {}
    for i, code in enumerate(blocks):
        try:
            exec(compile(code, f"{page}[block {i}]", "exec"), namespace)
        except Exception as err:
            raise AssertionError(f"{page}, block {i} failed:\n{code}") from err
    import matplotlib.pyplot as plt

    plt.close("all")


def test_api_reference_covers_public_api():
    text = api_reference()
    documented = {path.split(":")[1] for _, _, objects in SECTIONS for path in objects}
    assert set(iact_perf.__all__) - {"SCHEMA_VERSION"} <= documented
    for name in documented:
        assert f"### `{name}`" in text
    # pydantic's own docstring must not leak into models without a docstring
    assert "A base class for creating Pydantic models" not in text
    assert "`Database.query`" in text and "**filters" in text

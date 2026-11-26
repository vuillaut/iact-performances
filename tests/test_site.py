"""The website generator: JSON export and Zensical project."""

import json

import pytest

import iact_perf
from iact_perf.site.build import DEFAULT_CURVES, build
from iact_perf.site.export import export


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    path = tmp_path_factory.mktemp("site") / "records.json"
    summary = export(iact_perf.load(), path)
    return summary, json.loads(path.read_text())


def test_every_record_is_exported(data):
    summary, d = data
    assert summary["skipped"] == []
    assert len(d["records"]) == len(iact_perf.load())
    groups = {g["key"] for g in d["groups"]}
    assert all(r["group"] in groups for r in d["records"])


def test_sensitivities_share_one_unit(data):
    _, d = data
    sens = [
        r
        for r in d["records"]
        if r["quantity"] == "sensitivity" and r["integration"] == "differential"
    ]
    assert {r["group"] for r in sens} == {"sensitivity|differential|erg / (s cm2)"}
    crab = [r for r in sens if r["converted"] and "Crab" in r["converted"]]
    assert crab, "MAGIC values in % C.U. must be converted"


def test_points_are_consistent(data):
    _, d = data
    for r in d["records"]:
        n = len(r["x"])
        assert len(r["y"]) == n
        for k in ("xlo", "xhi", "ylo", "yhi"):
            assert k not in r or len(r[k]) == n
        if "xlo" in r:
            assert all(lo <= x <= hi for lo, x, hi in zip(r["xlo"], r["x"], r["xhi"], strict=True))


def test_default_curves_exist(data):
    _, d = data
    uids = {r["uid"]: r["group"] for r in d["records"]}
    assert all(u in uids for u in DEFAULT_CURVES)
    assert len({uids[u] for u in DEFAULT_CURVES}) == 1  # one plot


def test_build_project(tmp_path):
    out = tmp_path / "site"
    build(out=out)
    docs = out / "docs"
    import tomllib

    config = tomllib.loads((out / "zensical.toml").read_text())["project"]
    assert config["nav"][1] == {"Compare": "compare.md"}
    for page in (
        "index.md",
        "compare.md",
        "analyses.md",
        "sources/index.md",
        "about/contributing.md",
    ):
        assert (docs / page).exists(), page
    for slug in iact_perf.load().sources:
        assert (docs / "sources" / f"{slug}.md").exists()
        assert list((docs / "data" / "sources" / slug).glob("*.ecsv"))
    assert (docs / "assets" / "compare.js").exists()

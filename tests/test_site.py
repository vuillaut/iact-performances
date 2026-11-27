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
    exported = {r["uid"].removesuffix("@cu") for r in d["records"]}
    assert exported == {f"{r.source}/{r.id}" for r in iact_perf.load().records}
    groups = {g["key"] for g in d["groups"]}
    assert all(r["group"] in groups for r in d["records"])


def test_sensitivities_share_one_unit(data):
    _, d = data
    sens = [
        r
        for r in d["records"]
        if r["quantity"] == "sensitivity"
        and r["integration"] == "differential"
        and not r["group"].endswith("% CU")
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
    guide = config["nav"][2]["User guide"]
    assert guide[0] == {"Getting started": "user/index.md"}
    assert guide[-1] == {"API reference": "user/api.md"}
    for page in (
        "index.md",
        "compare.md",
        "analyses.md",
        "sources/index.md",
        "about/contributing.md",
        "user/index.md",
        "user/how-to/compare.md",
        "user/api.md",
    ):
        assert (docs / page).exists(), page
    for slug in iact_perf.load().sources:
        assert (docs / "sources" / f"{slug}.md").exists()
        assert list((docs / "data" / "sources" / slug).glob("*.ecsv"))
    assert (docs / "assets" / "compare.js").exists()
    # the script must go through extra_javascript: a <script src> written in
    # compare.md was resolved outside the site when it is served under a
    # subpath (GitHub Pages)
    assert "assets/compare.js" in config["extra_javascript"]
    assert "compare.js" not in (docs / "compare.md").read_text()


def test_crab_unit_group(data):
    _, d = data
    cu = [r for r in d["records"] if r["group"] == "sensitivity|differential|% CU"]
    sources = {r["source"] for r in cu}
    assert {"lst1_abe2023_crab-performance", "magic_aleksic2016_performance-upgrade"} <= sources
    # LST-1 (observed Crab) is only in the % C.U. group; MAGIC (model) is in both
    lst = [
        r
        for r in d["records"]
        if r["source"] == "lst1_abe2023_crab-performance" and r["quantity"] == "sensitivity"
    ]
    assert {r["group"] for r in lst} == {"sensitivity|differential|% CU"}
    assert not any(r["uid"].endswith("@cu") for r in lst)  # its only entry keeps the plain id
    magic_uids = {
        r["uid"]
        for r in d["records"]
        if r["source"].startswith("magic") and r["quantity"] == "sensitivity"
    }
    assert any(uid.endswith("@cu") for uid in magic_uids)
    assert len({r["uid"] for r in d["records"]}) == len(d["records"])  # uids stay unique

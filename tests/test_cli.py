import shutil

import pytest

from iact_perf.catalog import default_root
from iact_perf.cli import main
from iact_perf.reproduce import compare

ROOT = default_root()
MAGIC = "magic_aleksic2016_performance-upgrade"


@pytest.fixture
def repo_copy(tmp_path):
    for d in ("instruments", "references", "sources", "schema"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def test_validate(capsys):
    assert main(["validate"]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_fails(repo_copy, capsys):
    (repo_copy / "sources" / MAGIC / "source.yaml").write_text("title: x\n")
    assert main(["--root", str(repo_copy), "validate"]) == 1
    assert "source.yaml" in capsys.readouterr().out


def test_list(capsys):
    assert main(["list", "--quantity", "angular_resolution", "--instrument", "magic"]) == 0
    out = capsys.readouterr().out
    assert "\n4 record(s)" in out
    assert "containment_68" in out
    assert main(["list", "--analysis", "freepact", "--quantity", "energy_bias"]) == 0
    assert "\n5 record(s)" in capsys.readouterr().out


def test_new(repo_copy, capsys):
    assert main(["--root", str(repo_copy), "new", "veritas_doe2020_performance"]) == 0
    src = repo_copy / "sources" / "veritas_doe2020_performance"
    assert (src / "source.yaml").exists() and (src / "extract.py").exists()
    out = capsys.readouterr().out
    assert "instruments/veritas.yaml does not exist" in out
    # the template must not pass validation before it is filled
    assert main(["--root", str(repo_copy), "validate"]) == 1
    assert main(["--root", str(repo_copy), "new", "Bad Slug"]) == 1


def test_compare_reports_differences(tmp_path):
    committed = ROOT / "sources" / MAGIC
    produced = tmp_path / "produced"
    shutil.copytree(committed, produced)
    (produced / "energy_bias_gaussian-mean_zd00-30.ecsv").unlink()
    path = produced / "energy_resolution_rms_zd00-30.ecsv"
    path.write_text(path.read_text().replace("22.5 0.4 0.4", "22.6 0.4 0.4"))
    (produced / "new_record.ecsv").write_text("x")

    result = compare(MAGIC, committed, produced)
    assert not result.ok
    assert result.missing == ["energy_bias_gaussian-mean_zd00-30.ecsv"]
    assert result.extra == ["new_record.ecsv"]
    assert result.changed == {"energy_resolution_rms_zd00-30.ecsv": "values of value"}
    assert "DIFFERS" in result.report()

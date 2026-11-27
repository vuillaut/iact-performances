"""Validation of the database files committed in the repository."""

import json
import shutil

import pytest

from iact_perf.catalog import default_root, load_source, source_dirs, validate_repository
from iact_perf.reproduce import reproduce
from iact_perf.schema import MODELS

ROOT = default_root()


def test_repository_is_valid():
    assert validate_repository(ROOT) == []


def test_json_schemas_are_up_to_date():
    for name, model in MODELS.items():
        path = ROOT / "schema" / f"{name}.schema.json"
        assert json.loads(path.read_text()) == model.model_json_schema(), (
            f"{path.name} is outdated: run `uv run iact-perf export-schema`"
        )


@pytest.fixture
def repo_copy(tmp_path):
    for d in ("instruments", "references", "sources"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def test_detects_forbidden_files(repo_copy):
    (repo_copy / "sources" / "magic_aleksic2016_performance-upgrade" / "paper.pdf").touch()
    errors = validate_repository(repo_copy)
    assert any(".pdf files must not be committed" in e for e in errors)


def test_detects_bad_slug_and_unknown_instrument(repo_copy):
    src = repo_copy / "sources" / "magic_aleksic2016_performance-upgrade"
    src.rename(repo_copy / "sources" / "veritas_aleksic2016_performance")
    errors = validate_repository(repo_copy)
    assert any("slug starts with 'veritas'" in e for e in errors)


def test_detects_unknown_analysis_and_old_schema(repo_copy):
    reg = repo_copy / "references" / "analyses.yaml"
    reg.write_text(reg.read_text().replace("id: freepact\n", "id: freepact-v2\n"))
    src = repo_copy / "sources" / "magic_aleksic2016_performance-upgrade" / "source.yaml"
    src.write_text(src.read_text().replace('schema_version: "0.2"', 'schema_version: "0.1"'))
    errors = validate_repository(repo_copy)
    assert any("unknown analysis 'freepact'" in e for e in errors)
    assert any("schema_version '0.1'" in e for e in errors)


def test_detects_unknown_configuration(repo_copy):
    inst = repo_copy / "instruments" / "magic.yaml"
    inst.write_text(inst.read_text().replace("id: stereo_upgraded", "id: stereo_new"))
    errors = validate_repository(repo_copy)
    assert any("no configuration 'stereo_upgraded'" in e for e in errors)


@pytest.mark.network
@pytest.mark.parametrize("path", source_dirs(ROOT), ids=lambda p: p.name)
def test_reproduce(path):
    """Re-run extract.py of every reproducible source and compare with the committed records."""
    if not load_source(path).source.reproducible:
        pytest.skip("not reproducible")
    result = reproduce(path.name, ROOT)
    assert result.ok, result.report()

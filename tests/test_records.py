import astropy.units as u
import numpy as np
import pytest
from test_schema import record, sensitivity

from iact_perf.records import read_record, write_record

CU = u.Unit("CU")


def test_roundtrip(tmp_path):
    meta = record()
    cols = {
        "energy": [95, 150] * u.GeV,
        "value": [0.157, 0.135] * u.deg,
        "value_err_low": [0.007, 0.005] * u.deg,
        "value_err_high": [0.007, 0.006] * u.deg,
    }
    path = write_record(tmp_path / "r.ecsv", cols, meta)
    rec = read_record(path)
    assert rec.meta == meta
    assert rec.id == "r"
    assert rec.table["value"].unit == u.deg
    np.testing.assert_allclose(rec.table["value_err_high"].value, [0.007, 0.006])


def test_scaled_and_crab_units_roundtrip(tmp_path):
    flux = u.Unit("1e-12 cm-2 s-1 TeV-1")
    cols = {"energy_min": [63] * u.GeV, "energy_max": [100] * u.GeV, "value": [730] * flux}
    rec = read_record(write_record(tmp_path / "f.ecsv", cols, sensitivity()))
    assert rec.table["value"].unit == flux
    assert rec.table["value"][0].to_value("cm-2 s-1 TeV-1") == pytest.approx(7.3e-10)

    cols["value"] = [6.7] * u.percent * CU
    meta = sensitivity(crab_reference="magic_aleksic2016")
    rec = read_record(write_record(tmp_path / "c.ecsv", cols, meta))
    assert rec.table["value"].unit.is_equivalent(CU)


@pytest.mark.parametrize(
    "cols, meta, match",
    [
        ({"energy": [1] * u.TeV, "value": [0.1] * u.m}, record(), "not valid for"),
        ({"value": [0.1] * u.deg}, record(), "needs 'energy'"),
        ({"energy": [1] * u.m, "value": [0.1] * u.deg}, record(), "not an energy"),
        (
            {"energy": [1] * u.TeV, "value": [0.1] * u.deg, "value_err_low": [-0.01] * u.deg},
            record(),
            "must be positive",
        ),
        (
            {"energy_min": [2] * u.TeV, "energy_max": [1] * u.TeV, "value": [0.1] * u.deg},
            record(),
            "below",
        ),
        ({"energy_min": [1] * u.TeV, "value": [0.1] * u.deg}, record(), "go together"),
        (
            {"energy": [1] * u.TeV, "value": [5] * u.percent * CU},
            sensitivity(),
            "crab_reference",
        ),
        ({"energy": [1] * u.TeV, "value": [1] * u.deg, "foo": [1] * u.deg}, record(), "unknown"),
    ],
)
def test_invalid_columns(tmp_path, cols, meta, match):
    with pytest.raises(ValueError, match=match):
        write_record(tmp_path / "bad.ecsv", cols, meta)
    assert not (tmp_path / "bad.ecsv").exists()

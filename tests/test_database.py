import astropy.units as u
import numpy as np
import pytest

import iact_perf
from iact_perf import crab

MAGIC = "magic_aleksic2016_performance-upgrade"


@pytest.fixture(scope="module")
def db():
    return iact_perf.load()


def test_load(db):
    assert len(db) >= 38
    assert "magic" in db.instruments
    assert MAGIC in db.sources
    assert "magic_aleksic2016" in db.crab_spectra


def test_query(db):
    recs = db.query(quantity="sensitivity", instrument="magic", energy_integration="differential")
    assert len(recs) == 10
    assert all(r.meta.energy_integration == "differential" for r in recs)

    low = db.query(
        quantity="angular_resolution",
        definition="containment_68",
        zenith="20 deg",
        instrument="magic",
    )
    assert [r.id for r in low] == ["angular_resolution_containment-68_zd00-30"]

    both = db.query(
        quantity="angular_resolution",
        definition="containment_68",
        zenith=30 * u.deg,
        instrument="magic",
    )
    assert len(both) == 2  # zenith ranges include their bounds

    assert db.query(quantity=["energy_bias", "energy_resolution"], source=MAGIC, zenith="40 deg")
    assert len(db.query(quantity="sensitivity", observation_time="3000 min")) == 20
    assert db.query(quantity="sensitivity", where=lambda r: len(r.table) > 100) == []


def test_query_by_instrument_and_analysis(db):
    recs = db.query(instrument="ctao", analysis="freepact", quantity="angular_resolution")
    assert len(recs) == 5  # full array 20 deg, with g/h cut, MST, SST, 50 deg
    assert {r.meta.configuration for r in recs} == {
        "south_alpha",
        "south_alpha_mst",
        "south_alpha_sst",
    }
    both = db.query(analysis=["freepact", "impact"], zenith="50 deg", quantity="energy_bias")
    assert {r.meta.analysis for r in both} == {"freepact", "impact"}
    assert db.query(instrument="magic", analysis="freepact") == []
    assert "freepact" in db.analyses


def test_query_rejects_unknown_filter(db):
    with pytest.raises(TypeError, match="unknown filters"):
        db.query(zenith_angle="20 deg")


def test_superseded(db, monkeypatch):
    rec = db.query(source=MAGIC)[0]
    source = db.sources[MAGIC]
    monkeypatch.setitem(db.sources, MAGIC, source.model_copy(update={"superseded_by": "x_y_z"}))
    assert db.query(source=MAGIC) == []
    assert rec in db.query(source=MAGIC, include_superseded=True)


def test_record_energy(db):
    rec = db.get(MAGIC, "sensitivity_differential_li-ma-3off_crab_zd00-30")
    np.testing.assert_allclose(rec.energy[0].to_value(u.GeV), np.sqrt(63 * 100))


@pytest.mark.parametrize("integration", ["differential", "integral"])
@pytest.mark.parametrize("zd", ["zd00-30", "zd30-45"])
def test_crab_conversion_matches_magic_tables(db, integration, zd):
    """The paper gives each sensitivity in C.U. and in absolute units: convert one into the other.

    The tolerance covers the rounding of the published values (e.g. '10 +- 3' % C.U.).
    """
    name = f"sensitivity_{integration}_excess-over-sqrt-bkg_{{}}_{zd}"
    in_cu = db.get(MAGIC, name.format("crab"))
    flux = db.get(MAGIC, name.format("flux"))
    converted = db.convert(in_cu, flux.table["value"].unit)
    ratio = (converted["value"] / flux.table["value"]).to_value(u.one)
    np.testing.assert_allclose(ratio, 1, atol=0.06)
    assert np.median(np.abs(ratio - 1)) < 0.02

    back = db.convert(flux, "% CU", crab_reference="magic_aleksic2016")
    np.testing.assert_allclose(back["value"].value, in_cu.table["value"].value, rtol=0.06)


def test_convert_errors_and_energy_flux(db):
    rec = db.get(MAGIC, "sensitivity_differential_li-ma-5off_crab_zd00-30")
    t = db.convert(rec, "erg cm-2 s-1")
    assert t["value"].unit == u.Unit("erg cm-2 s-1")
    rel = rec.table["value_err_high"] / rec.table["value"]
    np.testing.assert_allclose(t["value_err_high"] / t["value"], rel)
    # the record itself is untouched
    assert rec.table["value"].unit.is_equivalent(u.Unit("CU"))


def test_convert_non_sensitivity(db):
    rec = db.get(MAGIC, "angular_resolution_containment-68_zd00-30")
    t = db.convert(rec, "arcmin")
    np.testing.assert_allclose(t["value"].value, rec.table["value"].value * 60)
    np.testing.assert_allclose(t["value_err_low"].value, rec.table["value_err_low"].value * 60)


def test_convert_needs_crab_spectrum(db):
    rec = db.get(MAGIC, "sensitivity_integral_excess-over-sqrt-bkg_flux_zd00-30")
    with pytest.raises(ValueError, match="Crab spectrum"):
        db.convert(rec, "% CU")


def test_crab_integral_power_law():
    from iact_perf.schema import CrabSpectrum

    spec = CrabSpectrum(
        id="pl",
        description="d",
        reference="10.1/x",
        model="power_law",
        amplitude="1e-11 cm-2 s-1 TeV-1",
        reference_energy="1 TeV",
        index=2.5,
    )
    # analytic: A E0 / (index - 1) (E/E0)^(1 - index), up to 1000 TeV
    expected = 1e-11 / 1.5 * (1 - 1000**-1.5)
    assert crab.integral_flux(spec, 1 * u.TeV)[0].value == pytest.approx(expected, rel=1e-4)

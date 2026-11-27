import pytest
from pydantic import ValidationError

from iact_perf.schema import SLUG_RE, CrabSpectrum, RecordMeta, Source


def record(**kw):
    base = dict(
        schema_version="0.2",
        label="test",
        quantity="angular_resolution",
        definition="containment_68",
        energy_type="reconstructed",
        instrument="magic",
        configuration="stereo_upgraded",
        analysis="magic-mars-standard",
        data_kind="real_data",
        provenance={"method": "latex_table", "location": "Table 1"},
    )
    return RecordMeta(**(base | kw))


def sensitivity(**kw):
    criteria = dict(
        significance=5,
        significance_formula="li_ma_eq17",
        n_off_regions=3,
        min_excess=10,
        min_signal_to_background=0.05,
        bins_per_decade=5,
    )
    criteria.update(kw.pop("criteria", {}))
    base = dict(
        quantity="sensitivity",
        definition=None,
        energy_integration="differential",
        observation_time="50 h",
        sensitivity_criteria=criteria,
    )
    return record(**(base | kw))


def test_valid_records():
    assert record().conditions.zenith_range == "unknown"
    assert sensitivity().sensitivity_criteria.n_off_regions == 3
    integral = sensitivity(energy_integration="integral", criteria={"bins_per_decade": None})
    assert integral.sensitivity_criteria.bins_per_decade is None


@pytest.mark.parametrize(
    "kw, match",
    [
        ({"definition": None}, "needs a 'definition'"),
        ({"definition": "fwhm"}, "not allowed"),
        ({"energy_type": None}, "needs 'energy_type'"),
        ({"data_kind": "guess"}, "data_kind"),
        ({"conditions": {"zenith_range": ["0 deg", "30 m"]}}, "not convertible"),
        ({"conditions": {"offset": "0.4"}}, "not convertible"),
        ({"instrument": "MAGIC"}, "not a valid identifier"),
        ({"analysis": None}, "analysis"),
        ({"conditions": {"analysis": "MARS"}}, "Extra inputs"),
        ({"extra_field": 1}, "Extra inputs"),
    ],
)
def test_invalid_records(kw, match):
    with pytest.raises(ValidationError, match=match):
        record(**kw)


@pytest.mark.parametrize(
    "kw, match",
    [
        ({"observation_time": None}, "observation_time"),
        ({"sensitivity_criteria": None}, "sensitivity_criteria"),
        ({"energy_integration": None}, "energy_integration"),
        ({"criteria": {"bins_per_decade": None}}, "bins_per_decade"),
        ({"energy_integration": "integral"}, "does not apply"),
        ({"observation_time": "50"}, "not convertible"),
    ],
)
def test_invalid_sensitivities(kw, match):
    with pytest.raises(ValidationError, match=match):
        sensitivity(**kw)


def test_criteria_only_for_sensitivity():
    with pytest.raises(ValidationError, match="only applies"):
        record(
            sensitivity_criteria=dict(
                significance=5,
                significance_formula="unknown",
                min_excess="unknown",
                min_signal_to_background="none",
            )
        )


@pytest.mark.parametrize(
    "slug, ok",
    [
        ("magic_aleksic2016_performance-upgrade", True),
        ("ctao_prod6-v1.0_performance", True),
        ("lst1_abe2023_performance", True),
        ("MAGIC_aleksic2016_performance", False),
        ("magic_aleksic2016", False),
        ("magic_aleksic 2016_perf", False),
    ],
)
def test_slug(slug, ok):
    assert bool(SLUG_RE.match(slug)) == ok


def source(**kw):
    base = dict(
        schema_version="0.2",
        title="t",
        authors=["A. B."],
        year=2020,
        doi="10.1016/j.astropartphys.2015.02.005",
        source_type="article",
        refereed=True,
        instruments=["magic"],
        reproducible=False,
    )
    return Source(**{k: v for k, v in (base | kw).items() if v is not None})


def test_source_identifiers():
    source()
    source(doi=None, url="https://example.org/perf", accessed="2026-11-26")
    with pytest.raises(ValidationError, match="doi or a url"):
        source(doi=None)
    with pytest.raises(ValidationError, match="accessed"):
        source(doi=None, url="https://example.org/perf")
    with pytest.raises(ValidationError, match="not a DOI"):
        source(doi="arXiv:1409.5594")


def test_crab_spectrum_curvature():
    base = dict(
        id="x",
        description="d",
        reference="10.1/x",
        amplitude="3e-11 cm-2 s-1 TeV-1",
        reference_energy="1 TeV",
        index=2.5,
    )
    CrabSpectrum(model="power_law", **base)
    CrabSpectrum(model="log_parabola_log10", curvature=0.2, **base)
    with pytest.raises(ValidationError, match="curvature"):
        CrabSpectrum(model="log_parabola_log10", **base)
    with pytest.raises(ValidationError, match="not convertible"):
        CrabSpectrum(model="power_law", **(base | {"amplitude": "3e-11 cm-2 s-1"}))


def test_observed_crab_reference():
    base = dict(id="x", description="d", reference="10.1/x")
    CrabSpectrum(model="observed", **base)
    with pytest.raises(ValidationError, match="no spectral parameters"):
        CrabSpectrum(model="observed", index=2.5, **base)
    with pytest.raises(ValidationError, match="required"):
        CrabSpectrum(model="power_law", **base)

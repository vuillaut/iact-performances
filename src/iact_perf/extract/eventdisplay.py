"""Performance curves from the ROOT files of Eventdisplay IRF productions (CTAO Prod5, Prod6).

Each file holds the histograms of one IRF (site, zenith, azimuth, sky, array,
optimisation time). The energy axis of every histogram is log10(E/TeV), five
bins per decade (effective areas: ten). Empty bins are 0 in the file and mean
"no value": they are dropped.

The main histograms (no ``_offaxis`` suffix) are computed from gamma rays
simulated as a point source on the camera axis (``gamma_onSource`` in the
``IRFLog`` of the file).
"""

from __future__ import annotations

from dataclasses import dataclass

import astropy.units as u
import numpy as np

from .root import RootFile


@dataclass(frozen=True)
class Histogram:
    key: str  # histogram name in the file
    stem: str  # start of the record file name
    quantity: str
    definition: str | None
    unit: u.UnitBase
    energy_type: str | None  # None: depends on the release, see ``energy_axis``
    integration: str | None = None


#: Histograms shown in the official performance figures of the releases.
HISTOGRAMS = (
    Histogram("DiffSens", "sensitivity_differential", "sensitivity", None,
              u.Unit("erg cm-2 s-1"), "reconstructed", "differential"),
    Histogram("AngResEtrue", "angular_resolution_containment-68_etrue", "angular_resolution",
              "containment_68", u.deg, "true"),
    Histogram("AngRes", "angular_resolution_containment-68_ereco", "angular_resolution",
              "containment_68", u.deg, "reconstructed"),
    Histogram("ERes", "energy_resolution_containment-68", "energy_resolution",
              "containment_68", u.dimensionless_unscaled, None),
    Histogram("EffectiveAreaEtrueNoTheta2cut", "effective_area_no-direction-cut",
              "effective_area", "no_direction_cut", u.m**2, "true"),
    Histogram("EffectiveAreaEtrue", "effective_area_direction-cut", "effective_area",
              "direction_cut", u.m**2, "true"),
    Histogram("BGRatePerSqDeg", "background_rate", "background_rate", None,
              u.Unit("Hz deg-2"), "reconstructed", "differential"),
)  # fmt: skip

#: Axis titles of the histograms, and the energy type they declare.
AXIS_ENERGY_TYPE = {
    "log_{10} (E_{MC}/TeV)": "true",
    "log_{10} (E_{Rec}/TeV)": "reconstructed",
    "log_{10} (E/TeV)": None,  # the file does not say: use the release documentation
}


def as_float32_text(values) -> np.ndarray:
    """Values stored as float32 in the file, written with the shortest decimal
    that reads back to the same float32 (``0.055``, not ``0.0550000011920929``)."""
    return np.array([float(str(np.float32(v))) for v in values])


def read_curve(f: RootFile, h: Histogram, energy_type: str | None = None) -> dict | None:
    """Columns of one histogram (empty bins dropped), or None if it is absent or empty.

    ``energy_type`` is required when the histogram axis does not say it.
    """
    if h.key not in f:
        return None
    values, log_edges = f.histogram(h.key)
    declared = AXIS_ENERGY_TYPE.get(f.axis_title(h.key))
    if h.key not in ("DiffSens", "BGRatePerSqDeg", "ERes") and declared is None:
        raise ValueError(f"{h.key}: unexpected axis title {f.axis_title(h.key)!r}")
    if declared is not None and h.energy_type is not None and declared != h.energy_type:
        raise ValueError(f"{h.key}: axis says {declared} energy, expected {h.energy_type}")
    etype = h.energy_type or energy_type
    if etype is None:
        raise ValueError(f"{h.key}: give the energy type, the file does not say it")

    edges = np.round(np.asarray(log_edges, dtype=float), 6)
    keep = np.asarray(values) > 0
    if not keep.any():
        return None
    lo = 10 ** edges[:-1][keep]
    hi = 10 ** edges[1:][keep]
    return {
        "energy_type": etype,
        "n_empty": int((~keep).sum()),
        "columns": {
            "energy_min": _sig(lo) * u.TeV,
            "energy_max": _sig(hi) * u.TeV,
            "value": as_float32_text(np.asarray(values)[keep]) * h.unit,
        },
    }


def _sig(x, digits=6):
    return np.array([float(f"{v:.{digits}g}") for v in x])


# --------------------------------------------------------------------------- releases

DURATIONS = {"180000": "50 h", "18000": "5 h", "1800": "30 min", "100": "100 s"}
DURATION_TAGS = {"180000": "50h", "18000": "5h", "1800": "30min", "100": "100s"}

#: Sensitivity criteria stated in the release documentation of Prod5 (archived
#: web page) and Prod6 (README): 5 sigma, at least 10 gamma rays per bin,
#: signal/background >= 0.05, five bins per decade. The significance formula
#: and the number of OFF regions are not stated (IRFLog: alpha = 0.2).
SENSITIVITY_CRITERIA = {
    "significance": 5,
    "significance_formula": "unknown",
    "n_off_regions": "unknown",
    "min_excess": 10,
    "min_signal_to_background": 0.05,
    "bins_per_decade": 5,
}


def iter_release(archive, pattern, cache_select=None):
    """Yield ``(fields, RootFile)`` for every ROOT file of a release bundle whose
    name matches the regex ``pattern`` (named groups become ``fields``)."""
    import re

    from .zenodo import iter_archive

    regex = re.compile(pattern)
    for name, data in iter_archive(archive, lambda base: bool(regex.fullmatch(base))):
        fields = regex.fullmatch(name.rsplit("/", 1)[-1]).groupdict()
        with RootFile(data, name) as f:
            yield fields, f


def record_meta(
    h: Histogram,
    curve: dict,
    *,
    label: str,
    configuration: str,
    analysis: str,
    zenith: str,
    azimuth: str,
    moon: str,
    duration: str,
    analysis_details: str,
    cuts: str,
    location: str,
):
    """Header of one record of an Eventdisplay release."""
    from ..schema import SCHEMA_VERSION, RecordMeta

    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=label,
        quantity=h.quantity,
        definition=h.definition,
        energy_integration=h.integration,
        energy_type=curve["energy_type"],
        instrument="ctao",
        configuration=configuration,
        analysis=analysis,
        data_kind="monte_carlo",
        observation_time=duration,
        sensitivity_criteria=SENSITIVITY_CRITERIA if h.quantity == "sensitivity" else None,
        conditions={
            "zenith_range": [zenith, zenith],
            "azimuth": azimuth,
            "offset": "0 deg",
            "moon": moon,
            "analysis_details": analysis_details,
            "cuts": cuts,
        },
        provenance={
            "method": "official_data_file",
            "location": location,
            "original_column": f"histogram {h.key}",
        },
    )

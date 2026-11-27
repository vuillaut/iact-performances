"""Extract the performance figures of Parsons et al. 2015 (arXiv:1509.06322).

H.E.S.S. II data analysis with ImPACT, ICRC 2015 proceedings. The performance
on simulated gamma rays (20 deg zenith) is shown in four ROOT figures: effective
area and angular resolution (Figure 2), energy bias and energy resolution
(Figure 3), for three mono cut sets (Safe, Std, Loose) and the stereo analysis.
There are no tables and no data files: the curves are read from the vector PDFs
of the arXiv source with ``iact_perf.extract.rootpdf``.

Checks run on every extraction:

- the markers of each curve are the vertices of its polyline, and the legend
  matches the four expected series (Safe, Std, Loose, Stereo) by marker colour
  and shape; ``Eres.pdf`` has no legend and is identified by the markers of
  ``Ebias.pdf``, the other panel of the same figure;
- the tick labels of every axis lie on a line within ``TICK_TOLERANCE``;
- numbers of the text: Loose mono effective area of 1e4 m2 down to 30 GeV, mono
  angular resolution below 0.16 deg for Safe and Std over most of the energy
  range and about 0.2 deg for Loose, stereo better than mono in effective area
  above 300 GeV and in angular and energy resolution, mono energy bias positive
  at low energy and negative at high energy;
- the energies of ``Eres.pdf`` are energies of ``Ebias.pdf`` (same binning).

    python sources/hess_parsons2015_impact-hess2/extract.py
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u
import numpy as np

from iact_perf.extract.arxiv import read_file
from iact_perf.extract.rootpdf import RootFigure, round_sig
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

ARXIV = "1509.06322"
HERE = Path(__file__).parent

#: The four series, by legend text. ``cuts`` quotes the row of Table 1 (tab-cuts)
#: with the column headers as printed; ``curve`` describes the marker.
SERIES: dict[str, dict] = {
    "Safe Mono": {
        "tag": "mono-safe",
        "configuration": "hess2_mono",
        "method": "mono, Safe cuts",
        "curve": "black dashed curve with open circles (legend: Safe Mono)",
        "cuts": (
            "Table 1 (tab-cuts), 'ImPACT mono Safe': Amp 80, Npix 8, Local distance "
            "1.15 deg, theta^2 0.015 deg^2, zeta > 0.9, MSCW n/a, MSCL n/a"
        ),
    },
    "Std Mono": {
        "tag": "mono-std",
        "configuration": "hess2_mono",
        "method": "mono, Std cuts",
        "curve": "red dashed curve with open squares (legend: Std Mono)",
        "cuts": (
            "Table 1 (tab-cuts), 'ImPACT mono Std': Amp 60, Npix 6, Local distance "
            "1.15 deg, theta^2 0.024 deg^2, zeta > 0.78, MSCW n/a, MSCL n/a"
        ),
    },
    "Loose Mono": {
        "tag": "mono-loose",
        "configuration": "hess2_mono",
        "method": "mono, Loose cuts",
        "curve": "blue dashed curve with open triangles (legend: Loose Mono)",
        "cuts": (
            "Table 1 (tab-cuts), 'ImPACT mono Loose': Amp 40, Npix 4, Local distance "
            "1.15 deg, theta^2 0.045 deg^2, zeta > 0.44, MSCW n/a, MSCL n/a"
        ),
    },
    "Stereo": {
        "tag": "stereo",
        "configuration": "hess2_stereo",
        "method": "stereo",
        "curve": "green dashed curve with bold crosses (legend: Stereo)",
        "cuts": (
            "Table 1 (tab-cuts), 'ImPACT stereo': Amp 70, 75, Npix n/a, Local distance "
            "2 deg, 1.15 deg, theta^2 0.0075 deg^2, zeta n/a, MSCW < 0.6, MSCL < 1.9"
        ),
    },
}

MONO_DETAILS = (
    "ImPACT likelihood fit of the CT5 images only (images of the other telescopes "
    "removed), templates from Monte Carlo simulations; seeded by a Hillas-parameter mono "
    "analysis (both head-tail solutions tried, the one of highest likelihood kept); "
    "two-step fit (first all parameters free except Xmax, fixed at its expectation for "
    "the current energy, then the source position fixed); background rejection with "
    "neural networks trained on Hillas parameters (Murach et al., ICRC 2015)"
)
STEREO_DETAILS = (
    "ImPACT likelihood fit of events with images in at least two telescopes (CT5 and "
    "CT1-4, one template library per telescope type), seeded by the Hillas-parameter "
    "analysis, as for H.E.S.S. I; background rejection with box cuts on the mean scaled "
    "width and length (MSCW, MSCL)"
)

#: Quantities: the figure file, where it is in the paper, how to store it.
QUANTITIES: dict[str, dict] = {
    "effective_area": {
        "file": "Aeff.pdf",
        "location": "Figure 2, left (fig-performance, file Aeff.pdf)",
        "y_label": "Effective Area",
        "unit": u.m**2,
        "stem": "effective_area",
        "definition": "other",
        "what": "effective area",
        "original": "Effective Area",
        "notes": (
            "The y axis has no unit; m2 comes from the text ('10^4 m2 of effective "
            "area'). The paper does not say whether the theta^2 cut of Table 1 is "
            "applied to the effective area, hence the definition 'other'."
        ),
    },
    "angular_resolution": {
        "file": "PSF.pdf",
        "location": "Figure 2, right (fig-performance, file PSF.pdf)",
        "y_label": "Angular Resolution (68% Containment)",
        "unit": u.deg,
        "stem": "angular_resolution_containment-68",
        "definition": "containment_68",
        "what": "angular resolution, 68% containment radius from a double Gaussian fit",
        "original": "Angular Resolution (68% Containment)",
        "notes": (
            "68% containment radius calculated from a double Gaussian fit (caption). "
            "The y axis has no unit; degrees come from the text (0.16 deg)."
        ),
    },
    "energy_bias": {
        "file": "Ebias.pdf",
        "location": "Figure 3, left (fig-enperformance, file Ebias.pdf)",
        "y_label": "Energy Bias",
        "unit": u.dimensionless_unscaled,
        "stem": "energy_bias",
        "definition": "other",
        "what": "energy bias",
        "original": "Energy Bias",
        "notes": (
            "The paper does not define the energy bias (relative or absolute, mean or "
            "median), hence the definition 'other'. The y axis has no unit; the "
            "values range from -0.5 to 0.5, which suggests a relative bias."
        ),
    },
    "energy_resolution": {
        "file": "Eres.pdf",
        "location": "Figure 3, right (fig-enperformance, file Eres.pdf)",
        "y_label": "Energy Resolution",
        "unit": u.dimensionless_unscaled,
        "stem": "energy_resolution",
        "definition": "other",
        "what": "energy resolution",
        "original": "Energy Resolution",
        "notes": (
            "The paper does not define the energy resolution (Gaussian sigma, RMS or "
            "68% interval of the relative error), hence the definition 'other'. The y "
            "axis has no unit; the values range from 0.08 to 0.3, which suggests a "
            "relative resolution."
        ),
    },
}


def meta(name: str, series: dict, quantity: dict) -> RecordMeta:
    mono = series["configuration"] == "hess2_mono"
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=(
            f"H.E.S.S. II ImPACT ({series['method']}) {quantity['what']}, "
            "simulated gamma rays at 20 deg zenith"
        ),
        quantity=name,
        definition=quantity["definition"],
        energy_type="true",
        instrument="hess",
        configuration=series["configuration"],
        analysis="impact",
        data_kind="monte_carlo",
        conditions={
            "zenith_range": ("20 deg", "20 deg"),
            "azimuth": "unknown",
            "offset": "unknown",
            "moon": "unknown",
            "analysis_details": MONO_DETAILS if mono else STEREO_DETAILS,
            "cuts": series["cuts"],
        },
        provenance={
            "method": "vector_figure",
            "location": quantity["location"],
            "original_column": f"{quantity['original']}; {series['curve']}",
        },
        notes=quantity["notes"],
    )


def check_figure(fig: RootFigure, quantity: dict, legend_names: dict[tuple, str] | None):
    """Checks on one figure. Returns the legend of the figure (signature -> text)."""
    if fig.y_label != quantity["y_label"]:
        raise ValueError(f"{quantity['file']}: y label {fig.y_label!r}")
    curves = fig.curves()
    try:
        legend = dict(fig.legend())
    except ValueError as err:
        # only a figure without any legend may borrow the one of its sibling panel
        if legend_names is None or "no legend" not in str(err):
            raise
        legend = {sig: legend_names[sig] for sig in curves if sig in legend_names}
    if set(legend) != set(curves) or set(legend.values()) != set(SERIES):
        raise ValueError(
            f"{quantity['file']}: curves {sorted(curves)} do not match the legend {legend}"
        )
    return legend


def check_text_numbers(data: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]]) -> None:
    """Numbers quoted in the text of the paper (Performance, Simulated Data)."""
    energy, area = data["effective_area"]["Loose Mono"]
    # "retaining 10^4 m2 of effective area down to 30 GeV" with the loose cuts
    if not (0.025 <= energy[0] <= 0.04 and 0.9e4 <= area[0] <= 1.1e4):
        raise ValueError(f"loose mono effective area {area[0]} m2 at {energy[0]} TeV")
    # stereo has the largest effective area above 300 GeV
    e_st, a_st = data["effective_area"]["Stereo"]
    for tag in ("Safe Mono", "Std Mono", "Loose Mono"):
        e_m, a_m = data["effective_area"][tag]
        high = e_st > 0.3
        if not np.all(a_st[high] > np.interp(e_st[high], e_m, a_m)):
            raise ValueError(f"stereo effective area not above {tag} above 300 GeV")
    # "an angular resolution of below 0.16 deg for most of the energy range" (Safe, Std),
    # "~0.2 deg resolution of the loose cuts" (below 300 GeV, where the mono curves
    # are not yet limited by truncated images)
    for tag in ("Safe Mono", "Std Mono"):
        if np.median(data["angular_resolution"][tag][1]) >= 0.16:
            raise ValueError(f"{tag}: median angular resolution above 0.16 deg")
    e_l, r_l = data["angular_resolution"]["Loose Mono"]
    if not np.all((r_l[e_l < 0.3] >= 0.18) & (r_l[e_l < 0.3] <= 0.22)):
        raise ValueError("loose mono angular resolution is not about 0.2 deg below 300 GeV")
    # stereo resolutions are better than all mono ones at the same energy
    for name in ("angular_resolution", "energy_resolution"):
        e_st, r_st = data[name]["Stereo"]
        for tag in ("Safe Mono", "Std Mono", "Loose Mono"):
            e_m, r_m = data[name][tag]
            inside = (e_st >= e_m[0]) & (e_st <= e_m[-1])
            if not inside.any() or not np.all(r_st[inside] < np.interp(e_st[inside], e_m, r_m)):
                raise ValueError(f"stereo {name} not better than {tag}")
    # mono energy bias: overestimated at low energy, underestimated at high energy
    for tag in ("Safe Mono", "Std Mono", "Loose Mono"):
        _, bias = data["energy_bias"][tag]
        if not (bias[0] > 0 and bias[-1] < 0):
            raise ValueError(f"{tag}: energy bias does not go from positive to negative")


def check_same_binning(data) -> None:
    """The energy resolution and the energy bias are computed in the same energy bins."""
    for tag in SERIES:
        e_bias = data["energy_bias"][tag][0]
        for e in data["energy_resolution"][tag][0]:
            if np.min(np.abs(e / e_bias - 1)) > 0.015:
                raise ValueError(f"{tag}: energy {e} TeV of Eres.pdf is not in Ebias.pdf")


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Download the arXiv source into ``cache_dir`` and write every record into ``out``."""
    figures: dict[str, RootFigure] = {}
    legends: dict[str, dict[tuple, str]] = {}
    for name in ("effective_area", "angular_resolution", "energy_bias", "energy_resolution"):
        spec = QUANTITIES[name]
        figures[name] = RootFigure(read_file(ARXIV, spec["file"], cache_dir))
        # Eres.pdf has no legend: it is the right panel of the figure whose left panel
        # is Ebias.pdf, with the same markers
        shared = legends.get("energy_bias") if name == "energy_resolution" else None
        legends[name] = check_figure(figures[name], spec, shared)
    if len({tuple(sorted(l.items())) for l in legends.values()}) != 1:  # noqa: E741
        raise ValueError("the figures do not use the same markers for the same series")

    data: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    for name, fig in figures.items():
        data[name] = {}
        for sig, curve in fig.curves().items():
            data[name][legends[name][sig]] = (
                round_sig(10**curve.x_log10),
                round_sig(curve.y),
            )
    check_text_numbers(data)
    check_same_binning(data)

    for name, per_series in data.items():
        quantity = QUANTITIES[name]
        for legend_name, (energy, value) in per_series.items():
            series = SERIES[legend_name]
            write_record(
                out / f"{quantity['stem']}_zd20-{series['tag']}_impact.ecsv",
                {"energy": energy * u.TeV, "value": value * quantity["unit"]},
                meta(name, series, quantity),
            )


if __name__ == "__main__":
    extract()

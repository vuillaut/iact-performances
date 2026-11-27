"""Extract the performance figures of Parsons & Hinton 2014 (arXiv:1403.2993).

ImPACT, a template-based likelihood reconstruction, compared with the standard
H.E.S.S. Hillas reconstruction (standard and hard cuts), on simulated gamma rays
for the four-telescope H.E.S.S. I array. Four figures of the paper give curves
versus the simulated energy: angular resolution (Figure 4 left, ``Ang68.eps``),
energy bias and energy resolution (Figure 5, ``EnBias.eps``, ``EnRes.eps``) and
effective area (Figure 6 right, ``Aeff.eps``). They are ROOT figures in EPS
format: Ghostscript turns them into PDF pages, which
``iact_perf.extract.rootpdf`` reads (the markers are the points).

Checks run on every extraction:

- the markers of each curve are the vertices of its polyline, and the legend
  matches the three expected series (Hillas std, Hillas hard, ImPACT std) by
  marker colour and shape; ``EnRes.eps`` has no legend and is identified by
  the markers of ``EnBias.eps``, the other panel of the same figure;
- the tick labels of every axis lie on a line within ``TICK_TOLERANCE``;
- numbers of the text: ImPACT effective area within about 10 % of Hillas std,
  ImPACT bias below 5 % above 500 GeV, ImPACT energy resolution below both
  Hillas ones (but the last bin), with a gain of 30-50 % at low energy, ImPACT
  angular resolution below both Hillas ones;
- the energies of ``EnRes.eps`` are energies of ``EnBias.eps`` (same binning).

    python sources/hess_parsons2014_impact-performance/extract.py
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u
import numpy as np

from iact_perf.extract.arxiv import read_file
from iact_perf.extract.rootpdf import RootFigure, eps_to_pdf, round_sig
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

ARXIV = "1403.2993"
HERE = Path(__file__).parent

#: The three series, by legend text. ``cuts`` quotes the row of Table 1 (tab-cuts)
#: with the column headers as printed, and the centroid cut of the text.
CENTROID = "image centroid within 2 deg of the camera centre (text)"
SERIES: dict[str, dict] = {
    "Hillas std": {
        "tag": "std",
        "analysis": "hillas-tmva",
        "method": "Hillas, standard cuts",
        "curve": "black curve with open circles (legend: Hillas std)",
        "details": (
            "Standard H.E.S.S. Hillas-parameter reconstruction with multivariate "
            "(TMVA boosted decision trees) background rejection (Ohm et al. 2009); standard "
            "cuts, optimised for a source of 10% Crab strength with an E^-2.6 spectrum"
        ),
        "cuts": (
            "Table 1 (tab-cuts), 'Hillas Std': Amp 60 p.e., theta^2 0.0125 deg^2, "
            f"zeta 0.84; {CENTROID}"
        ),
    },
    "Hillas hard": {
        "tag": "hard",
        "analysis": "hillas-tmva",
        "method": "Hillas, hard cuts",
        "curve": "blue curve with open triangles (legend: Hillas hard)",
        "details": (
            "Standard H.E.S.S. Hillas-parameter reconstruction with multivariate "
            "(TMVA boosted decision trees) background rejection (Ohm et al. 2009); hard "
            "cuts, optimised for a source of 1% Crab strength with an E^-2 spectrum"
        ),
        "cuts": (
            "Table 1 (tab-cuts), 'Hillas Hard': Amp 160 p.e., theta^2 0.01 deg^2, "
            f"zeta 0.89; {CENTROID}"
        ),
    },
    "ImPACT std": {
        "tag": "std",
        "analysis": "impact",
        "method": "ImPACT, standard cuts",
        "curve": "red curve with open squares (legend: ImPACT std)",
        "details": (
            "ImPACT likelihood fit of the camera images to Monte Carlo image templates "
            "(CORSIKA and sim_telarray), seeded by the Hillas reconstruction; background "
            "rejection with boosted decision trees on the Hillas parameters; standard cuts, "
            "optimised for a source of 10% Crab strength with an E^-2.6 spectrum"
        ),
        "cuts": (
            "Table 1 (tab-cuts), 'ImPACT Std': Amp 60 p.e., theta^2 0.005 deg^2, "
            f"zeta 0.83; {CENTROID}"
        ),
    },
}

#: The simulations: 4 telescopes, mirrors at 70% of the nominal optical efficiency.
SIMULATION = (
    "Monte Carlo simulations of the four-telescope H.E.S.S. array with mirrors at 70% of "
    "their nominal optical efficiency (roughly the state of the array when written). "
)

#: Quantities: the figure file, where it is in the paper, how to store it.
QUANTITIES: dict[str, dict] = {
    "effective_area": {
        "file": "Aeff.eps",
        "location": "Figure 6, right (fig-Xmax, file Aeff.eps)",
        "y_label": ")2Effective Area (m",  # ROOT writes the "2" of m^2 before the title
        "unit": u.m**2,
        "stem": "effective_area",
        "definition": "other",
        "zenith": "unknown",
        "what": "effective area",
        "original": "Effective Area (m^2)",
        "notes": (
            "'Effective collection area of the array as a function of energy for the "
            "three sets of cuts/reconstruction methods considered', after background "
            "rejection cuts (text). The paper does not say whether the theta^2 cut of "
            "Table 1 is applied, hence the definition 'other', nor the zenith angle."
        ),
    },
    "angular_resolution": {
        "file": "Ang68.eps",
        "location": "Figure 4, left (fig-angZen, file Ang68.eps)",
        "y_label": "Angular Resolution (deg)",
        "unit": u.deg,
        "stem": "angular_resolution_containment-68",
        "definition": "containment_68",
        "zenith": "20 deg",
        "what": "angular resolution (68% containment radius)",
        "original": "Angular Resolution (deg)",
        "notes": (
            "Caption: 'Angular resolution (68% containment radius) of the ImPACT method "
            "versus simulated energy at 20 deg zenith angle (left)'. The spectrum average "
            "of the caption ('averaging over a spectrum of the form dN/dE ~ E^-2') is "
            "stated for the zenith-angle panel; the paper does not say if it also applies "
            "to the energy panel."
        ),
    },
    "energy_bias": {
        "file": "EnBias.eps",
        "location": "Figure 5, left (fig-Eres, file EnBias.eps)",
        "y_label": "Energy Bias",
        "unit": u.dimensionless_unscaled,
        "stem": "energy_bias",
        "definition": "mean",
        "zenith": "unknown",
        "what": "energy bias",
        "original": "Energy Bias",
        "notes": (
            "Mean of the fractional deviation of the reconstructed energy from the "
            "simulated energy (text: 'fractional deviation of the reconstructed energy "
            "from the simulated energy ... shows the mean (energy bias)'). The paper does "
            "not give the zenith angle of the figure."
        ),
    },
    "energy_resolution": {
        "file": "EnRes.eps",
        "location": "Figure 5, right (fig-Eres, file EnRes.eps)",
        "y_label": "Energy Resolution",
        "unit": u.dimensionless_unscaled,
        "stem": "energy_resolution",
        "definition": "rms",
        "zenith": "unknown",
        "what": "energy resolution",
        "original": "Energy Resolution",
        "notes": (
            "RMS of the fractional deviation of the reconstructed energy from the "
            "simulated energy (text: '... shows the mean (energy bias) and RMS (energy "
            "resolution) of this distribution'). The paper does not give the zenith "
            "angle of the figure."
        ),
    },
}


def meta(name: str, series: dict, quantity: dict) -> RecordMeta:
    zenith = quantity["zenith"]
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=(
            f"H.E.S.S. I {series['method']} {quantity['what']}, simulated gamma rays"
            + (f" at {zenith} zenith" if zenith != "unknown" else "")
        ),
        quantity=name,
        definition=quantity["definition"],
        energy_type="true",
        instrument="hess",
        configuration="hess1_stereo",
        analysis=series["analysis"],
        data_kind="monte_carlo",
        conditions={
            "zenith_range": "unknown" if zenith == "unknown" else (zenith, zenith),
            "azimuth": "unknown",
            "offset": "unknown",
            "moon": "unknown",
            "analysis_details": SIMULATION + series["details"],
            "cuts": series["cuts"],
        },
        provenance={
            "method": "vector_figure",
            "location": quantity["location"],
            "original_column": f"{quantity['original']}; {series['curve']}",
        },
        notes=quantity["notes"],
    )


def figure(name: str) -> RootFigure:
    return RootFigure(eps_to_pdf(read_file(ARXIV, QUANTITIES[name]["file"])))


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


def _below(a, b) -> np.ndarray:
    """``a`` (energy, value) minus the curve ``b`` at the energies of ``a`` inside ``b``."""
    inside = (a[0] >= b[0][0]) & (a[0] <= b[0][-1])  # no extrapolation
    return (a[1] - np.interp(a[0], b[0], b[1]))[inside]


def check_text_numbers(data: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]]) -> None:
    """Numbers quoted in the text of the paper (Performance)."""
    imp = {name: data[name]["ImPACT std"] for name in data}
    std = {name: data[name]["Hillas std"] for name in data}
    hard = {name: data[name]["Hillas hard"] for name in data}
    # "a deficit of less than 10% seen across the full energy range" (effective area).
    # The figure does not follow the sentence to the letter: two of 38 points are more
    # than 10% below Hillas std (0.896 at 0.24 TeV, 0.833 at 66 TeV), see the notes.
    # Check the sentence within the scatter of the points.
    ratio = imp["effective_area"][1] / np.interp(imp["effective_area"][0], *std["effective_area"])
    if not (np.all(ratio > 0.8) and np.sum(ratio < 0.9) <= 2 and np.median(ratio) > 0.95):
        raise ValueError(f"ImPACT effective area is {ratio.min():.2f} of Hillas std")
    # "a clear improvement in angle resolution over the Hillas std" (and hard)
    for other in (std, hard):
        if not np.all(_below(imp["angular_resolution"], other["angular_resolution"]) < 0):
            raise ValueError("ImPACT angular resolution is not below Hillas")
    # "almost zero bias above 500 GeV ... smaller than 5%" (ImPACT)
    e, bias = imp["energy_bias"]
    if not np.all(np.abs(bias[e > 0.5]) < 0.05):
        raise ValueError("ImPACT energy bias above 5% above 500 GeV")
    # "significantly lower than the Hillas methods at all energies": true below the last
    # bin; in the last bin (79 TeV) ImPACT is 0.108 against 0.104 and 0.098 (see the notes)
    for other in (std, hard):
        diff = _below(imp["energy_resolution"], other["energy_resolution"])
        if not (np.all(diff[:-1] < 0) and diff[-1] > 0):
            raise ValueError("ImPACT energy resolution is not below Hillas below the last bin")
    # "the largest improvement at low energies (around 50%)": the figure gives 21% in the
    # first bin and at most 37% (0.5 TeV) relative to Hillas std, not 50% (see the notes);
    # check that the improvement is large (above 30%) at some energy below 1 TeV
    e, res = imp["energy_resolution"]
    gain = 1 - res / np.interp(e, *std["energy_resolution"])
    if not 0.3 < gain[e < 1].max() < 0.5:
        raise ValueError(f"largest energy resolution gain below 1 TeV is {gain[e < 1].max():.2f}")


def check_same_binning(data) -> None:
    """The energy resolution and the energy bias are computed in the same energy bins.

    The bias panel lacks the lowest points of the Hillas curves (off the visible axis,
    so not drawn by ROOT): the energies of the bias must be energies of the resolution,
    and only the lowest energies of the resolution may be missing from the bias.
    """
    for tag in SERIES:
        e_res = data["energy_resolution"][tag][0]
        e_bias = data["energy_bias"][tag][0]
        for e in e_bias:
            if np.min(np.abs(e / e_res - 1)) > 0.015:
                raise ValueError(f"{tag}: energy {e} TeV of EnBias.eps is not in EnRes.eps")
        missing = [e for e in e_res if np.min(np.abs(e / e_bias - 1)) > 0.015]
        if any(e > e_bias[0] for e in missing):
            raise ValueError(f"{tag}: energies of EnRes.eps missing in EnBias.eps: {missing}")


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Read the figures of the arXiv source and write every record into ``out``."""
    figures: dict[str, RootFigure] = {}
    legends: dict[str, dict[tuple, str]] = {}
    for name in ("effective_area", "angular_resolution", "energy_bias", "energy_resolution"):
        figures[name] = figure(name)
        # EnRes.eps has no legend: it is the right panel of the figure whose left panel
        # is EnBias.eps, with the same markers
        shared = legends.get("energy_bias") if name == "energy_resolution" else None
        legends[name] = check_figure(figures[name], QUANTITIES[name], shared)
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
        zenith = "zd20-" if quantity["zenith"] == "20 deg" else ""
        for legend_name, (energy, value) in per_series.items():
            series = SERIES[legend_name]
            write_record(
                out / f"{quantity['stem']}_{zenith}{series['tag']}_{series['analysis']}.ecsv",
                {"energy": energy * u.TeV, "value": value * quantity["unit"]},
                meta(name, series, quantity),
            )


if __name__ == "__main__":
    extract()

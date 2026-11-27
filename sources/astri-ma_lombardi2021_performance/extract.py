"""Extract the performance figures of Lombardi et al. 2021, PoS(ICRC2021)884.

Performance of the ASTRI Mini-Array at the Observatorio del Teide (ICRC 2021
proceedings). The values exist only as ROOT figures (TGraphErrors written by
ROOT's TPDF driver) included in the PoS PDF; there is no arXiv version, and the
ASTRI IRF release on Zenodo (10.5281/zenodo.6827882) holds IRFs, not these
curves. The figures are read from the PDF with ``iact_perf.extract.rootgraph``:

- Figure 2 (figure2_extended.pdf): on-axis differential sensitivity for 0.5, 5,
  50, 200 and 500 h;
- Figure 3 (figure3a.pdf, figure3b.pdf): on-axis angular and energy
  resolution, cuts optimised for the sensitivity in 50 h (grey points) and
  cuts that also weigh the resolution (dashed dark green line);
- Figure 4 (figure4.pdf, left pad): differential sensitivity in 50 h for five
  off-axis bins. The right pad (ratio to the first off-axis bin) is a ratio of
  the left-pad curves, used as a check, not stored.

Checks run on every extraction:

- the legends match the expected series; in Figure 4 the 0.5 deg series has no
  marker in the legend (its ratio is the line at 1) and is identified as the
  only other series of the left pad, then confirmed by the next check;
- Figure 4: the ratios of the right pad equal S(0.5 deg) / S(k) of the left pad
  (the caption: "higher values correspond to better performance");
- Figures 2 and 4: the Crab guide lines are 0.01 to 100 times
  E^2 dF/dE of the Crab spectrum of Albert et al. 2008 (reference [25] of the
  caption): this checks both axes with curves the calibration did not use;
- Figure 3: the dashed light green lines are at 3 arcmin and 10 % (caption);
- the bins are 0.2 decade wide with edges at log10(E/TeV) = 0.1 + 0.2 k (5 bins
  per decade, the binning of the ASTRI IRFs on Zenodo);
- the text: "an angular and energy resolution of a few arcmin and ~10% above a
  few TeV".

    python sources/astri-ma_lombardi2021_performance/extract.py
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u
import numpy as np

from iact_perf.catalog import default_root, load_crab_spectra
from iact_perf.crab import dnde
from iact_perf.extract.rootgraph import Graph, TPdfFigure, embedded_forms, round_sig
from iact_perf.extract.web import download
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

HERE = Path(__file__).parent
URL = "https://pos.sissa.it/395/884/pdf"
#: md5 of the PDF this script was written for (PoS, accessed 2026-11-27)
MD5 = "0e0cd303d462a90ccef54ae764cdaf82"
#: TPDF writes coordinates to 0.001 pt and the tick labels fit their ticks to
#: 0.0006 pt: 4 significant digits are safe (see notes in source.yaml)
DIGITS = 4

SENS_UNIT = u.erg / (u.cm**2 * u.s)
GREY_POINTS = (0.3, 0.3, 0.3)
CRAB_LINES = (0.68, 0.74, 0.78)
REFERENCE_LINE = (0.0, 1.0, 0.0)  # dashed light green, 3 arcmin / 10 %
RES_CUTS_LINE = (0.06, 0.54, 0.06)  # dashed dark green

#: Figure 2 legend -> observation time
ON_AXIS = {
    "ASTRI Mini-Array (0.5h)": ("0.5 h", "0.5h"),
    "ASTRI Mini-Array (5h)": ("5 h", "5h"),
    "ASTRI Mini-Array (50h)": ("50 h", "50h"),
    "ASTRI Mini-Array (200h)": ("200 h", "200h"),
    "ASTRI Mini-Array (500h)": ("500 h", "500h"),
}
#: Figure 4 legend -> off-axis angle, as printed
OFF_AXIS = {f"ASTRI Mini-Array (50h) {k}.5 degrees off-axis": f"{k}.5" for k in range(5)}

SIMULATION = (
    "A-SciSoft 0.3.1 on Monte Carlo simulations (CORSIKA, sim_telarray) of the nine "
    "telescopes at the Teide site, nominal pointing (all telescopes to the same "
    "position), dark-sky night sky background; random forests for gamma/hadron "
    "separation and energy, direction from the intersection of the image major axes; "
    "background (protons, electrons) reweighted to measured spectra; results averaged "
    "between the azimuths 0 and 180 deg"
)
AZIMUTH = "average of 0 and 180 deg (pointing to geomagnetic North and South)"
CRITERIA = {
    "significance": 5.0,
    "significance_formula": "li_ma_eq17",
    "n_off_regions": 5,
    "min_excess": 10.0,
    "min_signal_to_background": 0.05,
    "bins_per_decade": 5.0,
}


def sens_cuts(time: str) -> str:
    return (
        "cuts on background rejection, arrival direction and multiplicity optimised for "
        f"the differential flux sensitivity in {time}, in each energy bin and off-axis bin"
    )


RES_CUTS = {
    "angular_resolution": (
        "cuts optimised on both the differential flux sensitivity and the angular "
        "resolution (exposure time not stated)"
    ),
    "energy_resolution": (
        "cuts optimised on both the differential flux sensitivity and the energy "
        "resolution (exposure time not stated)"
    ),
}


# --------------------------------------------------------------------------- reading


def figures(cache_dir: Path | None) -> dict[str, TPdfFigure]:
    pdf = download(URL, "pos-icrc2021-884.pdf", MD5, cache_dir).read_bytes()
    forms = embedded_forms(pdf)
    names = ("figure2_extended.pdf", "figure3a.pdf", "figure3b.pdf", "figure4.pdf")
    return {name: TPdfFigure(forms[name]) for name in names}


def check_pad(fig: TPdfFigure, pad: int, y_title: str, log: bool) -> None:
    p = fig.pads[pad]
    if p.x_title != "log10(E [TeV])" or p.y_title != y_title or p.y.log != log:
        raise ValueError(f"pad {pad}: axes {p.x_title!r}, {p.y_title!r}, log={p.y.log}")


def check_bins(g: Graph, name: str) -> None:
    """Bins 0.2 decade wide, edges at log10(E/TeV) = 0.1 + 0.2 k, point at the bin centre."""
    for edges in (g.x_low, g.x_high):
        grid = (edges - 0.1) * 5
        if np.max(np.abs(grid - np.round(grid))) > 1e-4:
            raise ValueError(f"{name}: bin edges not on a 0.2-decade grid: {edges}")
    if np.max(np.abs(g.x_high - g.x_low - 0.2)) > 1e-4:
        raise ValueError(f"{name}: bins not 0.2 decade wide")
    if np.max(np.abs(g.x - (g.x_low + g.x_high) / 2)) > 1e-4:
        raise ValueError(f"{name}: points not at the centre of their bins")


#: The guide lines are drawn with 1 TeV = 1.6 erg, not 1.602177 erg: every line is
#: 10^k x this factor times the Crab, the same factor in Figures 2 and 4.
TEV_TO_ERG_AS_DRAWN = 1.6 / (1 * u.TeV).to_value(u.erg)


def check_crab_lines(fig: TPdfFigure, pad: int, name: str) -> None:
    """The grey guide lines are 10^k Crab of Albert et al. 2008 (E^2 dF/dE in erg).

    Each line must follow the shape of the spectrum (checks the x axis and the
    slope of the y axis) at a level 10^k (checks the offset of the y axis), up
    to the 1.6 erg/TeV of the plotting code; each "N Crab" label must sit on or
    just above the line of level N.
    """
    crab = next(s for s in load_crab_spectra(default_root()).spectra if s.id == "magic_albert2008")
    pad_ = fig.pads[pad]

    def in_crab(x, y):
        energy = 10 ** np.asarray(x) * u.TeV
        return y / (energy**2 * dnde(crab, energy)).to_value(SENS_UNIT) / TEV_TO_ERG_AS_DRAWN

    lines = fig.lines(pad, CRAB_LINES)
    if not lines:
        raise ValueError(f"{name}: no Crab guide line found")
    found = set()
    for x, y in lines:
        # the end vertices may be where ROOT clipped the line at the frame (on the
        # straight segment between two vertices, not on the curve): left out
        ratio = in_crab(x, y)[1:-1]
        if len(ratio) < 3 or np.max(ratio) / np.min(ratio) - 1 > 2e-4:
            raise ValueError(f"{name}: a Crab line does not follow the Crab shape: {ratio}")
        level = float(np.median(ratio))
        k = round(np.log10(level))
        if abs(level / 10**k - 1) > 2e-4:
            raise ValueError(f"{name}: Crab line at {level:.6g} Crab, not a power of ten")
        found.add(k)
    if not {-2, -1, 0, 1, 2} <= found:
        raise ValueError(f"{name}: Crab lines at 10^{sorted(found)}, expected 0.01 to 100 Crab")
    labels = [t for t in fig.texts if t.text.endswith(" Crab") and pad_.contains(t.x, t.y)]
    if len(labels) != 5:
        raise ValueError(f"{name}: {len(labels)} Crab labels")
    for t in labels:
        at = float(in_crab(pad_.x(t.x), pad_.y(t.y)))
        if not 1 <= at / float(t.text.split()[0]) < 1.3:
            raise ValueError(f"{name}: label {t.text!r} at {at:.3g} Crab")


def figure2(fig: TPdfFigure) -> dict[str, Graph]:
    check_pad(fig, 0, "E2 \xb4 Flux Sensitivity [erg cm-2 s-1]", log=True)
    legend = {text: sig for pad, sig, text in fig.legend() if pad == 0}
    if set(legend) != set(ON_AXIS):
        raise ValueError(f"Figure 2: legend {sorted(legend)}")
    graphs = fig.graphs(0)
    if set(graphs) != set(legend.values()):
        raise ValueError("Figure 2: graphs do not match the legend")
    check_crab_lines(fig, 0, "Figure 2")
    return {text: graphs[sig] for text, sig in legend.items()}


def figure3(fig: TPdfFigure, y_title: str, level: float, name: str) -> tuple[Graph, tuple]:
    """The grey points and the dashed dark green line of one panel of Figure 3."""
    check_pad(fig, 0, y_title, log=False)
    if _legend_or_none(fig):
        raise ValueError(f"{name}: unexpected legend {_legend_or_none(fig)}")
    graphs = fig.graphs(0)
    if len(graphs) != 1 or next(iter(graphs.values())).color != GREY_POINTS:
        raise ValueError(f"{name}: expected one grey graph, got {list(graphs)}")
    (ref,) = fig.lines(0, REFERENCE_LINE, min_vertices=2)
    if np.max(np.abs(ref[1] - level)) > 1e-5:
        raise ValueError(f"{name}: reference line at {ref[1]}, the caption says {level}")
    (line,) = fig.lines(0, RES_CUTS_LINE)
    return next(iter(graphs.values())), line


def _legend_or_none(fig: TPdfFigure) -> list:
    """Figure 3 has no legend (one series per panel, described by the caption)."""
    try:
        return fig.legend()
    except ValueError as err:
        if "no legend" in str(err):
            return []
        raise


def figure4(fig: TPdfFigure) -> dict[str, Graph]:
    check_pad(fig, 0, "E2 \xb4 Flux Sensitivity [erg cm-2 s-1]", log=True)
    check_pad(fig, 1, "Ratio", log=False)
    legend = {text: sig for pad, sig, text in fig.legend() if pad == 1}
    first = "ASTRI Mini-Array (50h) 0.5 degrees off-axis"
    if set(legend) != set(OFF_AXIS) - {first}:
        raise ValueError(f"Figure 4: legend {sorted(legend)}")
    if not any(t.text == first for t in fig.texts):
        raise ValueError("Figure 4: no legend text for the 0.5 deg bin")
    sens, ratio = fig.graphs(0), fig.graphs(1)
    others = [sig for sig in sens if sig not in legend.values()]
    if len(others) != 1 or set(ratio) != set(legend.values()):
        raise ValueError(f"Figure 4: graphs {list(sens)} / {list(ratio)} vs legend {legend}")
    out = {text: sens[sig] for text, sig in legend.items()}
    out[first] = sens[others[0]]
    check_ratios(out, {text: ratio[sig] for text, sig in legend.items()}, first)
    check_crab_lines(fig, 0, "Figure 4")
    return out


def check_ratios(sens: dict[str, Graph], ratio: dict[str, Graph], first: str) -> None:
    """Right pad of Figure 4: ratio_k = S(0.5 deg) / S(k), at the same energies."""
    ref = sens[first]
    for text, r in ratio.items():
        s = sens[text]
        if not (
            np.allclose(r.x, s.x, atol=1e-4) and np.isin(np.round(s.x, 3), np.round(ref.x, 3)).all()
        ):
            raise ValueError(f"Figure 4: {text}: ratio and sensitivity energies differ")
        expected = np.array([ref.y[np.argmin(np.abs(ref.x - x))] for x in s.x]) / s.y
        dev = np.max(np.abs(r.y / expected - 1))
        if dev > 1e-4:
            raise ValueError(f"Figure 4: {text}: ratio differs from S(0.5 deg)/S by {dev:.2g}")


def check_text(ang: Graph, eres: Graph) -> None:
    """'an angular and energy resolution of a few arcmin and ~10% above a few TeV'."""
    high = ang.x >= np.log10(3)
    arcmin = ang.y[high] * 60
    if not np.all((arcmin > 1) & (arcmin < 6)):
        raise ValueError(f"angular resolution above 3 TeV: {arcmin} arcmin")
    high = eres.x >= np.log10(3)
    if not np.all((eres.y[high] > 0.08) & (eres.y[high] < 0.15)):
        raise ValueError(f"energy resolution above 3 TeV: {eres.y[high]}")


# --------------------------------------------------------------------------- writing


def columns(g: Graph, unit) -> dict[str, u.Quantity]:
    """Energy, bin edges, value; y errors only if every point has both sides drawn."""
    out = {
        "energy": round_sig(10**g.x, DIGITS) * u.TeV,
        "energy_min": round_sig(10**g.x_low, DIGITS) * u.TeV,
        "energy_max": round_sig(10**g.x_high, DIGITS) * u.TeV,
        "value": round_sig(g.y, DIGITS) * unit,
    }
    if has_errors(g):
        out["value_err_low"] = round_sig(g.y_err_low, DIGITS) * unit
        out["value_err_high"] = round_sig(g.y_err_high, DIGITS) * unit
    return out


def has_errors(g: Graph) -> bool:
    return not (np.isnan(g.y_err_low).any() or np.isnan(g.y_err_high).any())


def meta(**kw) -> RecordMeta:
    conditions = {
        "zenith_range": ("20 deg", "20 deg"),
        "azimuth": AZIMUTH,
        "moon": "dark",
        "analysis_details": SIMULATION,
    }
    conditions.update(kw.pop("conditions"))
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        instrument="astri-ma",
        configuration="full_array",
        analysis="a-scisoft",
        data_kind="monte_carlo",
        energy_type="reconstructed",
        conditions=conditions,
        **kw,
    )


def error_note(g: Graph) -> str:
    if has_errors(g):
        return (
            "The y error bars are drawn on every point; the paper does not say what they represent."
        )
    return (
        "The figure draws a y error bar only where it is larger than the marker "
        f"({int(np.sum(~np.isnan(g.y_err_low)))} lower and "
        f"{int(np.sum(~np.isnan(g.y_err_high)))} upper sides of {len(g.x)} points): "
        "errors not extracted."
    )


def write_sensitivity(out: Path, g: Graph, time: str, tag: str, offset: str, location: str,
                      curve: str) -> None:  # fmt: skip
    on_axis = offset == "0"
    where = "on-axis point-like source" if on_axis else f"point-like source {offset} deg off-axis"
    write_record(
        out / f"sensitivity_differential_zd20-{'on-axis' if on_axis else f'off{offset}'}_{tag}.ecsv",
        columns(g, SENS_UNIT),
        meta(
            label=(
                f"ASTRI Mini-Array differential sensitivity, {where}, {time}, zenith 20 deg "
                "(MC, A-SciSoft)"
            ),
            quantity="sensitivity",
            energy_integration="differential",
            observation_time=time,
            sensitivity_criteria=CRITERIA,
            conditions={
                "offset": f"{offset} deg",
                "cuts": sens_cuts(time),
            },
            provenance={"method": "vector_figure", "location": location, "original_column": curve},
            notes=(
                ("" if on_axis else
                 f"Off-axis bin of 1 deg width centred on {offset} deg (five bins between "
                 "0 and 5 deg; the legend gives the centre). ")
                + error_note(g)
                + " Energies are the marker positions, energy_min/energy_max the ends of "
                "the horizontal error bars (reconstructed energy bins)."
            ),
        ),
    )  # fmt: skip


def write_resolution(out: Path, quantity: str, g: Graph, line: tuple, unit) -> None:
    spec = {
        "angular_resolution": (
            "angular_resolution_containment-68", "containment_68", "angular resolution",
            "Figure 3, left (figure3a.pdf)", "Angular Resolution [deg]",
            "68% gamma-ray containment radius",
        ),
        "energy_resolution": (
            "energy_resolution_gaussian-sigma", "gaussian_sigma", "energy resolution",
            "Figure 3, right (figure3b.pdf)", "Energy Resolution",
            "sigma of a Gaussian fit around the peak of E_reco/E_true, in each "
            "reconstructed-energy bin",
        ),
    }[quantity]  # fmt: skip
    stem, definition, what, location, axis, how = spec
    write_record(
        out / f"{stem}_zd20-on-axis_sens-cuts-50h.ecsv",
        columns(g, unit),
        meta(
            label=f"ASTRI Mini-Array on-axis {what}, cuts optimised for the sensitivity in 50 h",
            quantity=quantity,
            definition=definition,
            observation_time="50 h",
            conditions={"offset": "0 deg", "cuts": sens_cuts("50 h")},
            provenance={
                "method": "vector_figure",
                "location": location,
                "original_column": f"{axis}; dark grey points",
            },
            notes=(
                f"Definition from the text: {how}. The paper notes that these cuts do not "
                "give the best resolution achievable. " + error_note(g)
            ),
        ),
    )
    x, y = line
    write_record(
        out / f"{stem}_zd20-on-axis_res-cuts.ecsv",
        {"energy": round_sig(10**x, DIGITS) * u.TeV, "value": round_sig(y, DIGITS) * unit},
        meta(
            label=f"ASTRI Mini-Array on-axis {what}, cuts weighing sensitivity and resolution",
            quantity=quantity,
            definition=definition,
            conditions={"offset": "0 deg", "cuts": RES_CUTS[quantity]},
            provenance={
                "method": "vector_figure",
                "location": location,
                "original_column": f"{axis}; dashed dark green line",
            },
            notes=(
                f"Definition from the text: {how}. A line without markers or error bars: "
                "the energies are its vertices, which are the centres of the bins of the "
                "grey points (no bin edges given)."
            ),
        ),
    )


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Download the PoS PDF into ``cache_dir`` and write every record into ``out``."""
    figs = figures(cache_dir)
    on_axis = figure2(figs["figure2_extended.pdf"])
    ang, ang_line = figure3(figs["figure3a.pdf"], "Angular Resolution [deg]", 0.05, "Figure 3a")
    eres, eres_line = figure3(figs["figure3b.pdf"], "Energy Resolution", 0.1, "Figure 3b")
    off_axis = figure4(figs["figure4.pdf"])
    for name, g in [*on_axis.items(), *off_axis.items(), ("ang", ang), ("eres", eres)]:
        check_bins(g, name)
    for x, _ in (ang_line, eres_line):
        if not np.allclose(np.sort(x), ang.x, atol=1e-4):
            raise ValueError("dashed resolution line: vertices are not the bin centres")
    check_text(ang, eres)

    for text, g in on_axis.items():
        time, tag = ON_AXIS[text]
        write_sensitivity(out, g, time, tag, "0", "Figure 2 (figure2_extended.pdf)",
                          f"E2 x Flux Sensitivity [erg cm-2 s-1]; legend: {text}")  # fmt: skip
    for text, g in off_axis.items():
        legend = "" if OFF_AXIS[text] != "0.5" else (
            " (in the legend of the right pad only, as a line: identified as the remaining "
            "series of the left pad, checked with the ratios of the right pad)"
        )  # fmt: skip
        write_sensitivity(out, g, "50 h", "50h", OFF_AXIS[text], "Figure 4, left (figure4.pdf)",
                          f"E2 x Flux Sensitivity [erg cm-2 s-1]; legend: {text}{legend}")  # fmt: skip
    write_resolution(out, "angular_resolution", ang, ang_line, u.deg)
    write_resolution(out, "energy_resolution", eres, eres_line, u.dimensionless_unscaled)


if __name__ == "__main__":
    extract()

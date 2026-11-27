"""Extract the performance figures of Park et al. 2015 (arXiv:1508.07070).

Performance of the VERITAS experiment, ICRC 2015 proceedings (PoS(ICRC2015)771).
The arXiv e-print is a PDF made with Word; every figure is a ROOT plot embedded
as a bitmap (796 x 574 pixels, exact colours). There are no tables. The points
are the markers of the plots, read with ``iact_perf.extract.raster``.

Extracted (see ``source.yaml`` for what is not):

- Figure 1a: V6 differential sensitivity, soft and hard cuts (the medium curve
  is taken from Figure 1b, where none of its markers is covered);
- Figure 1b: V4, V5 and V6 differential sensitivity, medium cuts;
- Figure 4: V6 angular resolution (68 % containment), three cut sets;
- Figure 5a: V6 energy bias (median), three cut sets;
- Figure 5b: V6 energy resolution (68 % containment), three cut sets;
- Figure 6: V6 differential sensitivity, soft box cuts and soft BDT cuts.

The tick labels of each axis (``Axis``) and the legend texts are typed from the
figures: the digitizer cannot read text. It checks them against the tick marks
and the legend colours it finds. Checks run on every extraction:

- the md5 of the PDF, and one figure bitmap per expected panel on each page;
- the V6 medium curve of Figure 1a equals the one of Figure 1b (same data,
  other marker, other image) within one pixel;
- the energy bias and resolution of a cut set are given at the same energies
  (Figures 5a and 5b), within one pixel;
- every energy resolution value is within one pixel of a multiple of 0.02 (the
  values are quantized in the figure); a label list shifted by one tick step
  would fail this check;
- numbers of the text: hard cuts give the best sensitivity above 600 GeV
  (but not at 420 GeV), the soft curve reaches the lowest energy, the
  angular resolution is below 0.1 deg at 1 TeV, the energy resolution is
  about 15-20 % and rises to 20-30 % near 10 TeV, the bias is close to zero
  between 0.5 and 20 TeV, the BDT gain is the largest at the lowest energies;
  the best differential sensitivity is about 1 % of the Crab flux.

    python sources/veritas_park2015_performance/extract.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import astropy.units as u
import numpy as np

from iact_perf.extract.arxiv import download_source
from iact_perf.extract.raster import Axis, Markers, RasterFigure, pdf_images
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

ARXIV = "1508.07070"
#: md5 of the arXiv e-print (v2, a PDF) this script was written for
PDF_MD5 = "18b6bc31abb6b065c9d958728863ef22"
HERE = Path(__file__).parent

#: figure bitmaps per page, from left to right
PAGES = {3: ("fig1a", "fig1b"), 4: ("fig2a", "fig2b"), 5: ("fig3", "fig4"),
         6: ("fig5a", "fig5b"), 7: ("fig6",)}  # fmt: skip

ENERGY = Axis((0.1, 1, 10), log=True)
CRAB = Axis((0.01, 0.1, 1), log=True)
V6_CUTS = ["V6, Soft cuts", "V6, Medium cuts", "V6, Hard cuts"]

#: the figures read: axis labels and legend texts as printed (top to bottom)
FIGURES = {
    "fig1a": {"x": ENERGY, "y": CRAB, "legend": V6_CUTS, "where": "Figure 1 (a), page 3"},
    "fig1b": {
        "x": ENERGY,
        "y": CRAB,
        "legend": ["V4, Medium cuts", "V5, Medium cuts", "V6, Medium cuts"],
        "where": "Figure 1 (b), page 3",
    },
    "fig4": {
        "x": ENERGY,
        "y": Axis((0.08, 0.10, 0.12, 0.14, 0.16)),
        "legend": V6_CUTS,
        "where": "Figure 4, page 5",
    },
    "fig5a": {
        "x": ENERGY,
        "y": Axis(tuple(round(v, 1) for v in np.arange(-1, 1.01, 0.2))),
        "legend": V6_CUTS,
        "where": "Figure 5 (a), page 6",
    },
    "fig5b": {
        "x": ENERGY,
        "y": Axis(tuple(round(v, 2) for v in np.arange(0, 0.51, 0.05))),
        "legend": ["V6, Soft cuts", "V6, Med cuts", "V6, Hard cuts"],
        "where": "Figure 5 (b), page 6",
    },
    "fig6": {
        "x": ENERGY,
        "y": CRAB,
        "legend": ["V6, Soft cuts", "V6, Soft BDT cuts"],
        "where": "Figure 6, page 7",
    },
}

#: marker of each legend text, as drawn (for provenance.original_column)
MARKERS = {
    ("fig1a", "V6, Soft cuts"): "blue circles",
    ("fig1a", "V6, Hard cuts"): "red triangles",
    ("fig1a", "V6, Medium cuts"): "green squares",
    ("fig1b", "V4, Medium cuts"): "light green circles",
    ("fig1b", "V5, Medium cuts"): "green squares",
    ("fig1b", "V6, Medium cuts"): "dark green triangles",
    ("fig6", "V6, Soft cuts"): "blue circles",
    ("fig6", "V6, Soft BDT cuts"): "red squares",
}
for _fig in ("fig4", "fig5a", "fig5b"):
    for _text, _marker in zip(
        FIGURES[_fig]["legend"], ("blue circles", "green squares", "red triangles"), strict=True
    ):
        MARKERS[(_fig, _text)] = _marker

CUTS = {
    "soft": (
        "soft cuts: box cuts optimised for sources with a spectral index of -3.5 to -4.0, "
        "with a low energy threshold (cut values not given in the paper)"
    ),
    "medium": (
        "medium cuts: box cuts optimised for sources of 2-10 % of the Crab Nebula strength "
        "with an index of -2.5 to -3.0, adjusted to similar energy thresholds in all epochs "
        "(cut values not given in the paper)"
    ),
    "hard": (
        "hard cuts: box cuts optimised for sources weaker than 2 % of the Crab Nebula "
        "strength (purest gamma-ray sample, highest energy threshold of the three sets), "
        "adjusted to similar energy thresholds in all epochs (cut values not given in the "
        "paper)"
    ),
}
STANDARD = (
    "VERITAS standard analysis (Daniel et al. 2007): moment analysis, box cuts on scaled "
    "parameters, energy from look-up tables. The paper does not say which of the two "
    "VERITAS analysis packages made this figure; the cuts were used 'after consistency "
    "check with an independent analysis package'."
)
PACKAGE2 = (
    "Second VERITAS analysis package (not named in the paper): box cuts and BDT cuts "
    "are both defined and calculated with it (caption of Figure 6)."
)
BDT = (
    "Boosted decision trees (TMVA) trained on simulated gamma rays and real background "
    "events as a function of energy and elevation, using the standard Hillas parameters; "
    "cuts optimised for soft-index sources; second VERITAS analysis package (not named "
    "in the paper)."
)
SENSITIVITY = {
    "significance": 5.0,
    "significance_formula": "li_ma_eq17",
    "n_off_regions": "unknown",
    "min_excess": 10.0,
    "min_signal_to_background": "unknown",
}
SMALL_BIAS = "events with a small energy bias selected for the sensitivity calculation"


# --------------------------------------------------------------------------- reading


def load_figures(cache_dir: Path | None) -> dict[str, RasterFigure]:
    pdf = Path(download_source(ARXIV, cache_dir)).read_bytes()
    if hashlib.md5(pdf).hexdigest() != PDF_MD5:
        raise ValueError(f"arXiv:{ARXIV} e-print changed (md5), check the figures again")
    images = pdf_images(pdf)
    by_page: dict[int, list] = {}
    for im in images:
        by_page.setdefault(im.page, []).append(im)
    if sorted(by_page) != sorted(PAGES):
        raise ValueError(f"figure bitmaps on pages {sorted(by_page)}, expected {sorted(PAGES)}")
    named = {}
    for page, names in PAGES.items():
        ims = sorted(by_page[page], key=lambda im: im.bbox[0])
        if len(ims) != len(names):
            raise ValueError(f"page {page}: {len(ims)} figure bitmaps, expected {len(names)}")
        named.update(zip(names, ims, strict=True))
    return {
        name: RasterFigure(named[name].pixels, spec["x"], spec["y"], spec["legend"])
        for name, spec in FIGURES.items()
    }


def uncertainty(fig: RasterFigure, y_unit: str) -> str:
    """One pixel, in the units of each axis."""
    height, width, _ = fig.pixels.shape
    x_rel = 10**fig.x.pixel_size - 1
    if fig.y.log:
        y_text = f"{fig.y.pixel_size:.2g} in log10 of the value ({100 * (10**fig.y.pixel_size - 1):.2g} %)"
    else:
        y_text = f"{fig.y.pixel_size:.2g} {y_unit}".rstrip()
    return (
        f"Marker centres placed to about 1 pixel of the {width} x {height} pixel bitmap: "
        f"{fig.x.pixel_size:.2g} in log10(E/TeV) ({100 * x_rel:.2g} %), {y_text}. "
        f"Axis calibration on the tick marks: largest residual {fig.x.max_residual:.2f} "
        f"pixel (x), {fig.y.max_residual:.2f} pixel (y)."
    )


def series(fig: RasterFigure, text: str) -> Markers:
    m = fig.markers(text)
    if len(m.x) == 0:
        raise ValueError(f"{text}: no marker found")
    return m


def hidden(fig: RasterFigure, text: str, texts: list[str]) -> list[float]:
    """Energies where another series of the figure has a marker and ``text`` has none."""
    own = fig.markers(text).px[:, 1]
    others = np.concatenate([fig.markers(t).px[:, 1] for t in texts if t != text])
    cols = []
    for c in np.sort(others):
        if np.min(np.abs(own - c)) > 3 and (not cols or c - cols[-1] > 3):
            cols.append(c)
    return [float(v) for v in fig.x.round(fig.x.to_data(cols))]


# --------------------------------------------------------------------------- checks


def at(m: Markers, energy: float, tol: float = 0.05) -> float | None:
    """Value of the marker at ``energy`` (within ``tol`` relative), or None."""
    i = np.argmin(np.abs(np.log(m.x / energy)))
    return float(m.y[i]) if abs(m.x[i] / energy - 1) <= tol else None


def check_same_curve(a: Markers, b: Markers, fig: RasterFigure, what: str, min_common: int):
    """Two figures of the same curve: same points within one pixel (plus a marker
    reference offset of half a pixel between marker shapes)."""
    n = 0
    for x, y in zip(a.x, a.y, strict=True):
        i = np.argmin(np.abs(np.log10(b.x / x)))
        if abs(np.log10(b.x[i] / x)) <= 1.5 * fig.x.pixel_size:
            n += 1
            dy = abs(np.log10(b.y[i] / y)) if fig.y.log else abs(b.y[i] - y)
            if dy > 1.5 * fig.y.pixel_size:
                raise ValueError(f"{what}: {y} vs {b.y[i]} at {x} TeV")
    if n < min_common:
        raise ValueError(f"{what}: only {n} common points")


def check_text_numbers(data: dict[tuple[str, str], Markers]) -> None:
    soft, hard = data[("fig1a", "V6, Soft cuts")], data[("fig1a", "V6, Hard cuts")]
    medium = data[("fig1b", "V6, Medium cuts")]  # all its markers are visible there
    # "hard cuts provide the best sensitivity at energies higher than 600 GeV"
    for x, y in zip(hard.x, hard.y, strict=True):
        others = [v for v in (at(soft, x), at(medium, x)) if v is not None]
        if x > 0.6 and not all(y < v for v in others):
            raise ValueError(f"hard cuts not the best at {x} TeV")
    low = at(hard, 0.42)
    if low is None or not low > at(medium, 0.42):
        raise ValueError("hard cuts already the best at 420 GeV")
    # soft cuts: the lowest energy threshold (lowest-energy point of Figure 1a)
    if not soft.x[0] < min(hard.x[0], data[("fig1a", "V6, Medium cuts")].x[0]):
        raise ValueError("the soft curve does not reach the lowest energy")
    # abstract: "1 % of the Crab Nebula flux within 25 hours" (integral); the best
    # differential sensitivity in 50 h is of the same order
    best = min(soft.y.min(), medium.y.min(), hard.y.min())
    if not 0.008 <= best <= 0.013:
        raise ValueError(f"best differential sensitivity {best} C.U.")
    # "VERITAS has a 68% containment radius smaller than 0.1 deg at 1 TeV"
    for t in ("V6, Medium cuts", "V6, Hard cuts"):  # the soft marker at 1 TeV is covered
        v = at(data[("fig4", t)], 1.0)
        if v is None or not v < 0.1:
            raise ValueError(f"angular resolution {v} deg at 1 TeV ({t})")
    # "the energy resolution of VERITAS is about 15% - 20%" ... "increases up to 25%
    # at 10 TeV"
    for t in FIGURES["fig5b"]["legend"]:
        m = data[("fig5b", t)]
        mid = m.y[(m.x > 0.3) & (m.x < 3)]
        if len(mid) and not 0.14 <= np.median(mid) <= 0.20:
            raise ValueError(f"{t}: median energy resolution {np.median(mid)} at 0.3-3 TeV")
        near10 = m.y[(m.x > 8) & (m.x < 14)]
        if len(near10) and not np.all((near10 >= 0.2) & (near10 <= 0.3)):
            raise ValueError(f"{t}: energy resolution {near10} near 10 TeV")
    # "The energy bias is close to zero for events with energies roughly between the
    # energy threshold value ... and a few tens of TeV"
    checked = 0
    for t in V6_CUTS:  # the soft markers of this range are covered by the others
        m = data[("fig5a", t)]
        mid = m.y[(m.x > 0.5) & (m.x < 20)]
        checked += len(mid)
        if len(mid) and np.max(np.abs(mid)) > 0.1:
            raise ValueError(f"{t}: energy bias {mid} between 0.5 and 20 TeV")
    if checked < 10:
        raise ValueError(f"only {checked} energy bias points between 0.5 and 20 TeV")
    # BDT: "the improvement of the sensitivity ... is the most significant at low energy"
    box, bdt = data[("fig6", "V6, Soft cuts")], data[("fig6", "V6, Soft BDT cuts")]
    gain = {x: at(box, x) / y for x, y in zip(bdt.x, bdt.y, strict=True) if at(box, x)}
    if max(gain, key=gain.get) > 0.2:
        raise ValueError(f"largest BDT gain not at the lowest energies: {gain}")


def check_quantized_resolution(data, fig: RasterFigure) -> None:
    """Every energy resolution value is within one pixel of a multiple of 0.02."""
    for t in FIGURES["fig5b"]["legend"]:
        y = data[("fig5b", t)].y
        off = np.abs(y - 0.02 * np.round(y / 0.02))
        if np.any(off > fig.y.pixel_size):
            raise ValueError(f"{t}: energy resolution {y[off.argmax()]} off the 0.02 grid")


def check_same_binning(data, fig: RasterFigure) -> None:
    """Energy bias and resolution are given in the same true energy bins: every marker
    energy of Figure 5b is one of Figure 5a, and the other way round (any cut set,
    since markers covered in one figure may be visible in the other)."""
    tol = 1.5 * fig.x.pixel_size
    for a, b in (("fig5a", "fig5b"), ("fig5b", "fig5a")):
        bins = np.concatenate([m.x for (f, _), m in data.items() if f == b])
        for (f, text), m in data.items():
            if f != a:
                continue
            for e in m.x:
                if np.min(np.abs(np.log10(bins / e))) > tol:
                    raise ValueError(f"{a} {text}: energy {e} TeV is not a bin of {b}")


# --------------------------------------------------------------------------- records


RECORDS = [
    # (figure, legend text, cut set, configuration, analysis, file tag)
    ("fig1a", "V6, Soft cuts", "soft", "v6", "veritas-standard", "v6-soft"),
    ("fig1a", "V6, Hard cuts", "hard", "v6", "veritas-standard", "v6-hard"),
    ("fig1b", "V6, Medium cuts", "medium", "v6", "veritas-standard", "v6-medium"),
    ("fig1b", "V5, Medium cuts", "medium", "v5", "veritas-standard", "v5-medium"),
    ("fig1b", "V4, Medium cuts", "medium", "v4", "veritas-standard", "v4-medium"),
    ("fig4", "V6, Soft cuts", "soft", "v6", "veritas-standard", "v6-soft"),
    ("fig4", "V6, Medium cuts", "medium", "v6", "veritas-standard", "v6-medium"),
    ("fig4", "V6, Hard cuts", "hard", "v6", "veritas-standard", "v6-hard"),
    ("fig5a", "V6, Soft cuts", "soft", "v6", "veritas-standard", "v6-soft"),
    ("fig5a", "V6, Medium cuts", "medium", "v6", "veritas-standard", "v6-medium"),
    ("fig5a", "V6, Hard cuts", "hard", "v6", "veritas-standard", "v6-hard"),
    ("fig5b", "V6, Soft cuts", "soft", "v6", "veritas-standard", "v6-soft"),
    ("fig5b", "V6, Med cuts", "medium", "v6", "veritas-standard", "v6-medium"),
    ("fig5b", "V6, Hard cuts", "hard", "v6", "veritas-standard", "v6-hard"),
    ("fig6", "V6, Soft cuts", "soft", "v6", "veritas-standard", "v6-soft-package2"),
    ("fig6", "V6, Soft BDT cuts", "soft", "v6", "veritas-bdt", "v6-soft-bdt"),
]

QUANTITY = {
    "fig1a": "sensitivity",
    "fig1b": "sensitivity",
    "fig6": "sensitivity",
    "fig4": "angular_resolution",
    "fig5a": "energy_bias",
    "fig5b": "energy_resolution",
}


def describe(fig_name: str, text: str, cut: str, config: str, analysis: str) -> dict:
    """Metadata that depends on the figure: label, definition, conditions, ..."""
    epoch = config.upper()
    cut_words = f"{cut} cuts" if analysis == "veritas-standard" else f"{cut} BDT cuts"
    if fig_name in ("fig1a", "fig1b"):
        return {
            "label": (
                f"VERITAS {epoch} differential sensitivity (5 sigma, 50 h), {cut_words}, "
                "Crab data at elevation above 70 deg"
            ),
            "stem": "sensitivity_differential_zd00-20_50h",
            "unit": u.Unit("CU"),
            "y_name": "Source strength (Crab Unit)",
            "extra": {
                "energy_integration": "differential",
                "energy_type": "reconstructed",
                "data_kind": "real_data",
                "observation_time": "50 h",
                "sensitivity_criteria": {**SENSITIVITY, "bins_per_decade": 4},
                "crab_reference": "veritas_park2015_observed",
            },
            "conditions": {
                "zenith_range": ("0 deg", "20 deg"),
                "analysis_details": f"{STANDARD} {SMALL_BIAS[0].upper()}{SMALL_BIAS[1:]}.",
            },
            "notes": (
                "Differential sensitivity from Crab Nebula data with elevation higher than "
                "70 deg: the strength of a source, as a fraction of the Crab Nebula flux in "
                "each energy bin, detected at 5 sigma in 50 h (Li & Ma, at least 10 excess "
                "events per bin, four bins per decade). The energy is the position of the "
                "marker; the paper does not give the bin edges. The energy type is not "
                "stated: the bins of a sensitivity measured on data can only be in "
                "reconstructed energy. The error bars and the hatched bands are not "
                "extracted (the paper does not say what they show)."
            ),
        }
    if fig_name == "fig6":
        details = PACKAGE2 if analysis == "veritas-standard" else BDT
        return {
            "label": (
                f"VERITAS V6 differential sensitivity (5 sigma, 50 h), {cut_words} "
                "(second analysis package), Crab data at high elevation"
            ),
            "stem": "sensitivity_differential_50h",
            "unit": u.Unit("CU"),
            "y_name": "Source strength (Crab Unit)",
            "extra": {
                "energy_integration": "differential",
                "energy_type": "reconstructed",
                "data_kind": "real_data",
                "observation_time": "50 h",
                "sensitivity_criteria": {**SENSITIVITY, "bins_per_decade": "unknown"},
                "crab_reference": "veritas_park2015_observed",
            },
            "conditions": {
                "zenith_range": "unknown",
                "analysis_details": f"{details} {SMALL_BIAS[0].upper()}{SMALL_BIAS[1:]}.",
            },
            "notes": (
                "Caption of Figure 6: Crab data taken at high elevation, cuts optimised for "
                "soft index sources, 50 h, 'the same conditions described in Section 3' "
                "(5 sigma, Li & Ma, at least 10 excess events per bin, four bins per "
                "decade). The markers are 0.2 apart in log10(E), i.e. five per decade, not "
                "four: bins_per_decade is set to unknown. 'High elevation' is not "
                "quantified (Figure 1 uses elevation above 70 deg): zenith range unknown. "
                "The energy type is not stated (reconstructed, as for any sensitivity "
                "measured on data). Error bars not extracted."
            ),
        }
    sim = {
        "zenith_range": ("20 deg", "20 deg"),
        "analysis_details": STANDARD,
    }
    if fig_name == "fig4":
        return {
            "label": (
                f"VERITAS V6 angular resolution (68 % containment), {cut_words}, "
                "simulated gamma rays at 70 deg elevation"
            ),
            "stem": "angular_resolution_containment-68_zd20",
            "unit": u.deg,
            "y_name": "68% containment radius (deg)",
            "extra": {
                "definition": "containment_68",
                "energy_type": "reconstructed",
                "data_kind": "monte_carlo",
            },
            "conditions": sim,
            "notes": (
                "Radius containing 68 % of the simulated gamma-ray events of a point "
                "source in each energy bin, 70 deg elevation, events above the energy "
                "threshold. The x axis is E_REC (reconstructed energy)."
            ),
        }
    if fig_name == "fig5a":
        return {
            "label": (
                f"VERITAS V6 energy bias (median of (E_rec - E_true)/E_true), {cut_words}, "
                "simulated gamma rays at 70 deg elevation"
            ),
            "stem": "energy_bias_median_zd20",
            "unit": u.dimensionless_unscaled,
            "y_name": "(E_REC - E_true)/E_true",
            "extra": {
                "definition": "median",
                "energy_type": "true",
                "data_kind": "monte_carlo",
            },
            "conditions": sim,
            "notes": "Median of the (E_rec - E_true)/E_true distribution versus true energy.",
        }
    return {
        "label": (
            f"VERITAS V6 energy resolution (68 % containment around the median), {cut_words}, "
            "simulated gamma rays at 70 deg elevation"
        ),
        "stem": "energy_resolution_containment-68_zd20",
        "unit": u.dimensionless_unscaled,
        "y_name": "Energy resolution",
        "extra": {
            "definition": "containment_68",
            "energy_type": "true",
            "data_kind": "monte_carlo",
        },
        "conditions": {**sim, "cuts": None},
        "notes": (
            "68 % containment radius of the (E_rec - E_true)/E_true distribution around "
            "its median, versus true energy (caption of Figure 5). The values lie on a "
            "0.02 grid (checked by extract.py)."
        ),
    }


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Download the arXiv e-print into ``cache_dir`` and write every record into ``out``."""
    figs = load_figures(cache_dir)
    data = {
        (name, text): series(figs[name], text)
        for name, spec in FIGURES.items()
        for text in spec["legend"]
    }
    check_same_curve(
        data[("fig1a", "V6, Medium cuts")],
        data[("fig1b", "V6, Medium cuts")],
        figs["fig1a"],
        "V6 medium sensitivity, Figure 1a vs 1b",
        min_common=5,
    )
    check_same_binning(data, figs["fig5b"])
    check_quantized_resolution(data, figs["fig5b"])
    check_text_numbers(data)

    for fig_name, text, cut, config, analysis, tag in RECORDS:
        fig, m = figs[fig_name], data[(fig_name, text)]
        info = describe(fig_name, text, cut, config, analysis)
        missing = hidden(fig, text, FIGURES[fig_name]["legend"])
        notes = [info["notes"]]
        if missing:
            notes.append(
                "No visible marker of this series at E = "
                + ", ".join(f"{e:g}" for e in missing)
                + " TeV, where another series of the figure has one: covered by other "
                "markers, or no point; not extracted."
            )
        partial = m.visible < 0.8
        if partial.any():
            notes.append(
                f"{partial.sum()} marker(s) partly covered (visible fraction "
                f"{m.visible.min():.2f} to {m.visible[partial].max():.2f}), placed by their "
                "visible part."
            )
        if m.n_outside or m.n_covered:
            notes.append(
                f"Dropped: {m.n_outside} marker(s) centred outside the axes, "
                f"{m.n_covered} visible below 30 %."
            )
        if fig_name == "fig1b" and config == "v6":
            notes.append(
                "The same curve is drawn in Figure 1a (green squares, partly covered "
                "there); both readings agree within one pixel (checked by extract.py)."
            )
        conditions = dict(info["conditions"])
        conditions["cuts"] = (
            CUTS[cut]
            if analysis == "veritas-standard"
            else (
                "soft BDT cuts: BDT selection optimised for soft-index sources "
                "(cut values not given in the paper)"
            )
        )
        meta = RecordMeta(
            schema_version=SCHEMA_VERSION,
            label=info["label"],
            quantity=QUANTITY[fig_name],
            instrument="veritas",
            configuration=config,
            analysis=analysis,
            conditions=conditions,
            provenance={
                "method": "raster_digitized",
                "location": FIGURES[fig_name]["where"],
                "original_column": (
                    f"{info['y_name']}; {MARKERS[(fig_name, text)]} (legend: {text})"
                ),
                "digitization_uncertainty": uncertainty(figs[fig_name], str(info["unit"])),
            },
            notes=" ".join(notes),
            **info["extra"],
        )
        write_record(
            out / f"{info['stem']}_{tag}.ecsv",
            {
                "energy": figs[fig_name].x.round(m.x) * u.TeV,
                "value": figs[fig_name].y.round(m.y) * info["unit"],
            },
            meta,
        )


if __name__ == "__main__":
    extract()

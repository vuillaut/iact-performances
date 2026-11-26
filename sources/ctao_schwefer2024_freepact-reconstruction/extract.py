"""Extract the performance figures of Schwefer et al. 2024 (arXiv:2406.17502).

The paper presents the FreePACT event reconstruction and its performance on
Monte Carlo simulations of the CTAO southern array (Alpha configuration).
All its performance values are matplotlib vector PDF figures in the arXiv
source; there are no tables and no data files.

The curves are read from the PDF paths with ``iact_perf.extract.vector``.
Checks run on every extraction:

- the colour of every curve matches its legend entry;
- the right-hand axis of the angular resolution panels (arcmin) reads 60
  times the left-hand calibration (degrees): an independent check of the
  vertical calibration;
- points outside the visible axes are dropped (the reader cannot see them).

    python sources/ctao_schwefer2024_freepact-reconstruction/extract.py
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u

from iact_perf.extract.arxiv import read_file
from iact_perf.extract.vector import BLACK, Figure, round_sig
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

ARXIV = "2406.17502"
HERE = Path(__file__).parent

#: Stroke colours of the curves (rounded to 3 decimals), as given in the
#: captions; ``legend`` lists the legend texts allowed for each colour.
METHODS: dict[tuple[float, float, float], dict] = {
    (0.0, 0.333, 0.333): {
        "tag": "hillas-rf",
        "analysis": "ctapipe-hillas-rf",
        "legend": ("Hillas", "RandomForest"),
        "curve": "dark green curve (Hillas/Random Forest)",
        "method": "Hillas/Random Forest",
        "details": (
            "Hillas geometric direction reconstruction and Random Forest energy "
            "regression (ctapipe v0.20), also used as the seed of the likelihood fits"
        ),
    },
    (0.776, 0.827, 0.145): {
        "tag": "impact",
        "analysis": "impact",
        "legend": ("ImPACT",),
        "curve": "lime green curve (ImPACT)",
        "method": "ImPACT",
        "details": "ImPACT likelihood fit with the convolved analytical pixel PDF and classical templates",
    },
    (0.937, 0.486, 0.0): {
        "tag": "freepact",
        "analysis": "freepact",
        "legend": ("FreePACT",),
        "curve": "orange curve (FreePACT)",
        "method": "FreePACT",
        "details": "FreePACT likelihood fit (neural-network charge PDF, neural ratio estimation)",
    },
    (0.0, 0.694, 0.918): {
        "tag": "impact-freepact-templates",
        "analysis": "impact-freepact-templates",
        "legend": ("ImPACTfromFreePACT",),
        "curve": "light blue curve (ImPACT from FreePACT)",
        "method": "ImPACT from FreePACT",
        "details": "ImPACT likelihood fit with templates generated from the FreePACT models",
    },
}
AEFF_COLOR = (0.0, 0.424, 0.4)  # single curve of the effective-area figure
LEGEND = {color: m["legend"] for color, m in METHODS.items()}
LEGEND[BLACK] = ("CTAProd5Reference",)  # official Prod5 curves: not extracted here
LEGEND[AEFF_COLOR] = ("FullCTASoutharray",)

#: Panels, recognised by words of their y-axis label, and how to store them.
PANELS: dict[str, dict] = {
    "angular_resolution": {
        "label_words": ("containment", "deg"),
        "unit": u.deg,
        "definition": "containment_68",
        "stem": "angular_resolution_containment-68",
        "what": "angular resolution, 68% containment radius",
    },
    "energy_resolution": {
        "label_words": ("resolution",),
        "unit": u.dimensionless_unscaled,
        "definition": "containment_68",
        "stem": "energy_resolution_containment-68",
        "what": "energy resolution, half of the central 68% interval of (E_reco-E_true)/E_true",
    },
    "energy_bias": {
        "label_words": ("bias",),
        "unit": u.dimensionless_unscaled,
        "definition": "mean",
        "stem": "energy_bias_mean",
        "what": "energy bias, mean of (E_reco-E_true)/E_true",
    },
    "effective_area": {
        "label_words": ("area",),
        "unit": u.m**2,
        "definition": "no_direction_cut",
        "stem": "effective_area",
        "what": "on-axis effective area",
    },
}
RESOLUTION_PANELS = ("angular_resolution", "energy_resolution", "energy_bias")

#: Extracted figures: file in the arXiv source, place in the paper, conditions.
FIGURES: list[dict] = [
    {
        "file": "CTA_south_effective_area_4tel.pdf",
        "location": "Figure 3 (fig:cta_south_aeff)",
        "zenith": "20 deg",
        "configuration": "south_alpha",
        "tag": "zd20",
        "multiplicity": 4,
        "gh_cut": False,
        "panels": ("effective_area",),
    },
    {
        "file": "Full_CTA_resolution_curves_bounds_final_4tel.pdf",
        "location": "Figure 4 (fig:full_cta_resolution curves)",
        "zenith": "20 deg",
        "configuration": "south_alpha",
        "tag": "zd20",
        "multiplicity": 4,
        "gh_cut": False,
        "panels": RESOLUTION_PANELS,
    },
    {
        "file": "Full_CTA_resolution_curves_bound_75_cut_final_4tel.pdf",
        "location": "Figure 12 (fig:full_cta_resolution curves_gh_cut)",
        "zenith": "20 deg",
        "configuration": "south_alpha",
        "tag": "zd20-ghsep75",
        "multiplicity": 4,
        "gh_cut": True,
        "panels": RESOLUTION_PANELS,
    },
    {
        "file": "MST_resolution_curves_bounds_final_3tel.pdf",
        "location": "Figure 13 (fig:mst_resolution curves)",
        "zenith": "20 deg",
        "configuration": "south_alpha_mst",
        "tag": "zd20-mst-subarray",
        "multiplicity": 3,
        "gh_cut": False,
        "panels": RESOLUTION_PANELS,
    },
    {
        "file": "SST_resolution_curves_bounds_final_3tel.pdf",
        "location": "Figure 14 (fig:sst_resolution curves)",
        "zenith": "20 deg",
        "configuration": "south_alpha_sst",
        "tag": "zd20-sst-subarray",
        "multiplicity": 3,
        "gh_cut": False,
        "panels": RESOLUTION_PANELS,
    },
    {
        "file": "Full_CTA_resolution_curves_bounds_z50_final_4tel.pdf",
        "location": "Figure 15 (fig:full_cta_resolution curves_z50)",
        "zenith": "50 deg",
        "configuration": "south_alpha",
        "tag": "zd50",
        "multiplicity": 4,
        "gh_cut": False,
        "panels": RESOLUTION_PANELS,
    },
]

CUTS = (
    "at least {n} telescope images passing quality cuts: more than 3 pixels "
    "surviving image cleaning (tail-cuts 10/5 p.e.), intensity > 50 p.e., "
    "less than 10% of the intensity in the two outermost pixel rings, Hillas "
    "centroid within 3 deg of the camera centre; {gh}"
)
GH_NONE = "no gamma-hadron separation"
GH_75 = (
    "gamma-hadron separation cut at 75% gamma-ray efficiency "
    "(Random Forest classifier, 10 bins in reconstructed energy)"
)
CONFIG_NAME = {
    "south_alpha": "CTAO South Alpha full array",
    "south_alpha_mst": "CTAO South Alpha MST sub-array",
    "south_alpha_sst": "CTAO South Alpha SST sub-array",
}


def check_figure(fig: Figure, spec: dict) -> None:
    """Checks that do not depend on the extracted values being right."""
    for color, text in fig.legend():
        if color not in LEGEND or text not in LEGEND[color]:
            raise ValueError(f"{spec['file']}: legend entry {text!r} with colour {color}")
    if "angular_resolution" in spec["panels"]:
        ticks = fig.right_axis_ticks("angular_resolution")
        if len(ticks) < 2:
            raise ValueError(f"{spec['file']}: arcmin axis ticks not found")
        for arcmin, deg in ticks:
            if abs(deg * 60 / arcmin - 1) > 1e-4:
                raise ValueError(f"{spec['file']}: arcmin tick {arcmin} reads {deg * 60} arcmin")


def meta(spec: dict, panel: dict, method: dict | None) -> RecordMeta:
    zd = spec["zenith"].split()[0]
    config = spec["configuration"]
    cuts = CUTS.format(n=spec["multiplicity"], gh=GH_75 if spec["gh_cut"] else GH_NONE)
    if method is None:  # effective area: common to all reconstruction methods
        analysis = "schwefer2024-event-selection"
        details = (
            "image extraction and cleaning only (FlashCamExtractor for the MST, "
            "NeighborPeakWindowSum for the SST, tail-cuts 10/5 p.e.), before any "
            "reconstruction and before gamma-hadron separation"
        )
        label = (
            f"{CONFIG_NAME[config]} on-axis effective area before gamma-hadron "
            f"separation, event selection common to all reconstruction methods, {zd} deg zenith"
        )
        curve = "solid curve with round markers (Full CTA South array)"
    else:
        analysis, details, curve = method["analysis"], method["details"], method["curve"]
        label = (
            f"{CONFIG_NAME[config]} {panel['what']}, {method['method']} "
            f"reconstruction, on-axis, {zd} deg zenith"
        )
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=label,
        quantity=spec_quantity(panel),
        definition=panel["definition"],
        energy_type="true",
        instrument="ctao",
        configuration=config,
        analysis=analysis,
        data_kind="monte_carlo",
        conditions={
            "zenith_range": (spec["zenith"], spec["zenith"]),
            "azimuth": "unknown",
            "offset": "0 deg",
            "moon": "dark",
            "analysis_details": details,
            "cuts": cuts,
        },
        provenance={
            "method": "vector_figure",
            "location": spec["location"],
            "original_column": curve,
        },
    )


def spec_quantity(panel: dict) -> str:
    return next(k for k, v in PANELS.items() if v is panel)


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    for spec in FIGURES:
        labels = {k: PANELS[k]["label_words"] for k in spec["panels"]}
        fig = Figure(read_file(ARXIV, spec["file"], cache_dir), labels)
        check_figure(fig, spec)
        for name in spec["panels"]:
            panel = PANELS[name]
            curves = fig.curves(name)
            unexpected = set(curves) - set(LEGEND)
            if unexpected:
                raise ValueError(f"{spec['file']} {name}: unexpected curve colours {unexpected}")
            for color, curve in curves.items():
                if color == BLACK:
                    continue  # official Prod5 reference: belongs to its own source
                method = METHODS.get(color)  # None for the effective-area curve
                stem = f"{panel['stem']}_{spec['tag']}"
                name_ = f"{stem}_{method['tag']}" if method else stem
                write_record(
                    out / f"{name_}.ecsv",
                    {
                        "energy": round_sig(curve.x) * u.TeV,
                        "value": round_sig(curve.y) * panel["unit"],
                    },
                    meta(spec, panel, method),
                )


if __name__ == "__main__":
    extract()

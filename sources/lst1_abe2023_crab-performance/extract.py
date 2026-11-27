"""Extract the LST-1 performance of Abe et al. 2023 (ApJ 956, 80; arXiv:2306.12960).

The values come from the data repository of the paper,
github.com/cta-observatory/lst-crab-performance-paper-2023, archived on Zenodo
(v1.1.0, 10.5281/zenodo.8430774), read in memory:

- 6_results/6.1_flux_sensitivity/data/*.txt: differential sensitivity
  (Fig. 15), in % C.U., with the band of total uncertainty;
- 3_pipeline/3.4_irfs/irfs*/*.fits.gz: IRF tables written by pyirf
  (Figs. 4 and 5), for the files the figures use.

The selections are those of the notebooks that draw the paper figures:
sensitivity > 0 and 0.03 < E < 15 TeV (0.03-0.15 TeV without the 5 %
background condition); IRF tables without their first and last bins
(underflow 0-0.02 TeV, overflow 20 TeV-inf).

    python sources/lst1_abe2023_crab-performance/extract.py
"""

from __future__ import annotations

import gzip
import io
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy.table import QTable

from iact_perf.extract.zenodo import download, iter_archive
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

RECORD = 8430774
BUNDLE = "cta-observatory/lst-crab-performance-paper-2023-v1.1.0.zip"
ARCHIVE = "lst-crab-performance-paper-2023 v1.1.0 (10.5281/zenodo.8430774)"
HERE = Path(__file__).parent

ANALYSES = {
    "srcindep": ("lstchain-srcindep", "source-independent"),
    "srcdep": ("lstchain-srcdep", "source-dependent"),
}

# --------------------------------------------------------------------------- sensitivity

SENSITIVITY_FILES = {
    # file: (analysis, with the 5 % background condition, upper energy of the plotted curve)
    "sensitivity_src_indep.txt": ("srcindep", True, 15.0),
    "sensitivity_src_dep.txt": ("srcdep", True, 15.0),
    "sensitivity_src_indep_without_5percentbg.txt": ("srcindep", False, 0.15),
    "sensitivity_src_dep_without_5percentbg.txt": ("srcdep", False, 0.15),
}
E_MIN = 0.03  # TeV, lower energy of every plotted sensitivity curve


def sensitivity(files: dict[str, bytes], out: Path) -> None:
    for name, (tag, bkg5, e_max) in SENSITIVITY_FILES.items():
        data = np.loadtxt(io.BytesIO(files[name]))
        # columns: energy [TeV], sensitivity [% C.U.], (2 undocumented columns),
        # lower and upper edge of the total uncertainty band [% C.U.]
        energy, value, down, up = data[:, 0], data[:, 1], data[:, 4], data[:, 5]
        keep = (value > 0) & (energy > E_MIN) & (energy < e_max)
        if not keep.any():
            raise ValueError(f"{name}: no point in the plotted range")
        err_low, err_high = value[keep] - down[keep], up[keep] - value[keep]
        if (err_low < 0).any() or (err_high < 0).any():
            raise ValueError(f"{name}: band edges on the wrong side of the value")
        analysis, words = ANALYSES[tag]
        condition = "" if bkg5 else ", without the signal/background >= 5 % condition"
        meta = RecordMeta(
            schema_version=SCHEMA_VERSION,
            label=f"LST-1 differential sensitivity, 50 h, {words} analysis, Crab data at zenith < 35 deg{condition}",
            quantity="sensitivity",
            energy_integration="differential",
            energy_type="reconstructed",
            instrument="lst1",
            configuration="mono",
            analysis=analysis,
            data_kind="real_data",
            observation_time="50 h",
            sensitivity_criteria={
                "significance": 5,
                "significance_formula": "unknown",
                "n_off_regions": 5,  # "ON/OFF ratio of 0.2"
                "min_excess": 10,
                "min_signal_to_background": 0.05 if bkg5 else "none",
                "bins_per_decade": 5,
            },
            crab_reference="lst1_abe2023_observed",
            conditions={
                "zenith_range": ["0 deg", "35 deg"],
                "offset": "0.4 deg",
                "moon": "dark",
                "analysis_details": f"cta-lstchain v0.9.9, {words} analysis",
                "cuts": (
                    "gammaness and theta/alpha cuts optimised per energy bin on one half of "
                    "the Crab events, sensitivity computed on the other half"
                ),
            },
            provenance={
                "method": "official_data_file",
                "location": f"Figure 15 (fig:diff_sensitivity); {ARCHIVE}: "
                f"6_results/6.1_flux_sensitivity/data/{name}",
                "original_column": "columns 1 (sensitivity) and 5-6 (band edges, "
                "converted to error sizes), % C.U.",
            },
            notes=(
                "Errors are the total uncertainty band of the paper (statistics and a 1 % "
                "systematic uncertainty on the background normalisation)."
            ),
        )
        bkg = "" if bkg5 else "_no-5pc-bkg"
        write_record(
            out / f"sensitivity_differential_{tag}{bkg}_zd00-35_50h.ecsv",
            {
                "energy": energy[keep] * u.TeV,
                "value": value[keep] * u.percent * u.Unit("CU"),
                "value_err_low": err_low * u.percent * u.Unit("CU"),
                "value_err_high": err_high * u.percent * u.Unit("CU"),
            },
            meta,
        )


# --------------------------------------------------------------------------- IRFs

ZENITHS = ["10.00", "23.63", "32.06", "43.20"]
EFFICIENCIES = ["0.4", "0.7", "0.9"]
#: IRF files drawn in the paper: zenith 10 deg with three gamma efficiencies,
#: and gamma efficiency 70 % at four zenith angles (Figs. 4 and 5).
IRF_FILES = sorted({("10.00", e) for e in EFFICIENCIES} | {(z, "0.7") for z in ZENITHS})

CUTS = (
    "intensity > 50 p.e.; gammaness cut keeping {gh} % of the MC gamma rays in each "
    "bin of reconstructed energy{direction}"
)


def read_fits(data: bytes, hdu: str) -> QTable:
    return QTable.read(io.BytesIO(gzip.decompress(data)), hdu=hdu, format="fits")


def irf_meta(tag, zen, gh, quantity, definition, label, hdu, column, direction, figure):
    analysis, words = ANALYSES[tag]
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=f"LST-1 {label}, {words} analysis, zenith {float(zen):g} deg, "
        f"{float(gh) * 100:.0f} % gamma efficiency",
        quantity=quantity,
        definition=definition,
        energy_type="true",
        instrument="lst1",
        configuration="mono",
        analysis=analysis,
        data_kind="monte_carlo",
        conditions={
            "zenith_range": [f"{zen} deg", f"{zen} deg"],
            "offset": "0.4 deg",
            "moon": "dark",
            "analysis_details": f"cta-lstchain v0.9.9, {words} analysis; IRFs computed with pyirf",
            "cuts": CUTS.format(gh=round(float(gh) * 100), direction=direction),
        },
        provenance={
            "method": "official_data_file",
            "location": f"{figure}; {ARCHIVE}: {hdu}",
            "original_column": column,
        },
    )


def irfs(files: dict[str, bytes], out: Path) -> None:
    for zen, gh in IRF_FILES:
        g = f"gh{round(float(gh) * 100)}"
        zd = f"zd{zen.rstrip('0').rstrip('.')}"
        for tag in ("srcindep", "srcdep"):
            suffix = "_srcdep" if tag == "srcdep" else ""
            name = f"irfs_zen_{zen}_gh-eff_{gh}{suffix}.fits.gz"
            data = files[name]
            where = f"3_pipeline/3.4_irfs/irfs{suffix}/{name}"
            figure = (
                "Figure 5 (fig:irfs_src_dep)" if tag == "srcdep" else "Figure 4 (fig:irfs_srcindep)"
            )
            direction = (
                "; alpha cut keeping 70 % of the gamma rays (effective area, energy resolution and bias)"
                if tag == "srcdep"
                else "; theta cut keeping 70 % of the well-oriented gamma rays (effective area, "
                "energy resolution and bias)"
            )

            res = read_fits(data, "ENERGY_BIAS_RESOLUTION")[1:-1]  # drop under/overflow
            bins = {
                "energy_min": res["true_energy_low"],
                "energy_max": res["true_energy_high"],
                "energy": res["true_energy_center"],
            }
            for quantity, definition, column, label in (
                ("energy_resolution", "containment_68", "resolution",
                 "energy resolution, 68 % containment of |E_R - E_T|/E_T"),
                ("energy_bias", "median", "bias", "energy bias, median of (E_R - E_T)/E_T"),
            ):  # fmt: skip
                meta = irf_meta(tag, zen, gh, quantity, definition, label,
                                f"{where}, HDU ENERGY_BIAS_RESOLUTION", column, direction, figure)  # fmt: skip
                write_record(
                    out / f"{quantity}_{definition.replace('_', '-')}_{tag}_{zd}_{g}.ecsv",
                    bins | {"value": u.Quantity(res[column]) * u.one},
                    meta,
                )

            area = read_fits(data, "EFFECTIVE_AREA")[0]
            meta = irf_meta(
                tag, zen, gh, "effective_area",
                "other" if tag == "srcdep" else "direction_cut",
                "effective area", f"{where}, HDU EFFECTIVE_AREA", "EFFAREA", direction, figure,
            )  # fmt: skip
            write_record(
                out / f"effective_area_{tag}_{zd}_{g}.ecsv",
                {
                    "energy_min": area["ENERG_LO"][1:-1],
                    "energy_max": area["ENERG_HI"][1:-1],
                    "value": area["EFFAREA"].T[1:-1, 0],
                },
                meta,
            )

            if tag == "srcindep":  # no angular resolution in the source-dependent analysis
                ang = read_fits(data, "ANGULAR_RESOLUTION")[1:-1]
                meta = irf_meta(
                    tag, zen, gh, "angular_resolution", "containment_68",
                    "angular resolution, 68 % containment of well-oriented gamma rays",
                    f"{where}, HDU ANGULAR_RESOLUTION", "angular_resolution",
                    "; computed on the well-oriented gamma rays only (correct head-tail)", figure,
                )  # fmt: skip
                write_record(
                    out / f"angular_resolution_containment-68_{tag}_{zd}_{g}.ecsv",
                    {
                        "energy_min": ang["true_energy_low"],
                        "energy_max": ang["true_energy_high"],
                        "energy": ang["true_energy_center"],
                        "value": ang["angular_resolution"],
                    },
                    meta,
                )


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    bundle = download(RECORD, BUNDLE, cache_dir)
    wanted = set(SENSITIVITY_FILES) | {
        f"irfs_zen_{z}_gh-eff_{e}{s}.fits.gz" for z, e in IRF_FILES for s in ("", "_srcdep")
    }
    files = {Path(n).name: d for n, d in iter_archive(bundle, lambda base: base in wanted)}
    missing = wanted - set(files)
    if missing:
        raise FileNotFoundError(f"not in {BUNDLE}: {sorted(missing)}")
    sensitivity(files, out)
    irfs(files, out)


if __name__ == "__main__":
    extract()

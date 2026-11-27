"""Extract the gamma-PhysNet performance of Dell'Aiera et al. 2026
(Astron. Comput. 57, 101176; arXiv:2608.09630).

The paper publishes its LST-1 metrics integrated over energy and refers the
reader to its supplementary data repository for the energy-resolved IRFs.
The values come from that repository (GitLab, tag v2.1.0, the version archived
on Zenodo as 10.5281/zenodo.21824932). Only the 5 files needed are downloaded,
from the pinned commit, and checked against their sha256; the 2.2 GB Zenodo
archive is not needed (these files are byte-identical in it):

- irfs/vanilla/best_scenario/seed_{0..4}/irfs.fits.gz: IRFs of the vanilla
  gamma-PhysNet on clean simulations (best scenario), the curves the
  repository's "Comparison with lstchain" page is made of.

The curves are merged over the 5 seeds exactly as the published figures
merge them (girfs): the mean, with the min and max over the seeds as the
band. The under- and overflow bins are dropped, as in every published
curve (girfs remove_overflow_bins=True).

    python sources/lst1_dellaiera2026_domain-adaptation/extract.py
"""

from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path

import astropy.units as u
import numpy as np
import requests
from astropy.io import fits

from iact_perf.extract.zenodo import USER_AGENT, default_cache
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

REPO = "https://gitlab.in2p3.fr/gammalearn/publications/2024_domain_adaptation_methods"
COMMIT = "01915ad706b42482d151dd966ecb146ec73104bb"  # tag v2.1.0
ARCHIVE = f"GitLab repository {REPO}, tag v2.1.0 (archived as 10.5281/zenodo.21824932)"
HERE = Path(__file__).parent

# file path in the repository -> sha256 of the file
SHA256 = {
    f"irfs/vanilla/best_scenario/seed_{i}/irfs.fits.gz": h
    for i, h in enumerate(
        [
            "e7ff34f66bbf7d539a36ab39040acd388be493885c1dd25817cd258d661c85cb",
            "26f3f357227bcd7d4d22a75092fe5f6f2c146a555ebba3fa2359ba3e09aef227",
            "9cbbe3e629f2fd135b5ea7cd6fb444dfff983cf4e18497688858cda368a5dadf",
            "36ba3aa187f5aedd749762ea181ece4752de88f231d849b768de6f2b1bf66d03",
            "06ac13d5da17b374bc62fc6f72fd5fd960f4ee4702b6a3ff00a98d6682795840",
        ]
    )
}
FILES = list(SHA256)
SEEDS = [f"seed_{i}" for i in range(5)]


def fetch(cache_dir: Path | None) -> dict[str, bytes]:
    """Download the 5 seed files from the pinned commit into the cache, check sha256."""
    root = (Path(cache_dir) if cache_dir else default_cache()) / "gitlab" / COMMIT
    files = {}
    for name, sha in SHA256.items():
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            resp = requests.get(
                f"{REPO}/-/raw/{COMMIT}/{name}", headers={"User-Agent": USER_AGENT}, timeout=120
            )
            resp.raise_for_status()
            path.write_bytes(resp.content)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise OSError(f"{name}: sha256 differs from the pinned file")
        files[name] = data
    return files


ANALYSIS_DETAILS = (
    "GammaLearn v0.14.0, gamma-PhysNet multitask network (3.5 M parameters), vanilla version "
    "(no domain adaptation) trained on clean Prod5 LST-1 mono-trigger simulations "
    "(CORSIKA + sim_telarray, dl1 charge integration), training run R_1974, test run R_1975 "
    "of the provenance report of the archive; IRFs computed with pyirf (girfs v0.1.0) on the "
    "labelled test simulations (1.1 M point-source gammas, 0.76 M protons); value is the mean "
    "over 5 training seeds, the errors the min-max band over the seeds"
)
GH_CUT = "gammaness cut keeping 70 % of the MC gamma rays in each bin of true energy"


def seed_tables(files: dict[str, bytes]) -> list[fits.HDUList]:
    """Open the 5 seed files and check the structures the checks below rely on."""
    if set(files) != set(FILES):
        raise FileNotFoundError(f"expected exactly {FILES}, got {sorted(files)}")
    out = []
    for name in FILES:  # seed order
        hdul = fits.open(io.BytesIO(gzip.decompress(files[name])))
        for hdu in (
            "GH_CUTS",
            "EFFECTIVE_AREA",
            "EFFECTIVE_AREA_ANG_RES",
            "ANGULAR_RESOLUTION",
            "ENERGY_BIAS_RESOLUTION",
        ):
            if hdu not in hdul:
                raise KeyError(f"{name}: no {hdu} HDU")
        out.append(hdul)
    return out


def same_bins(seeds: list[fits.HDUList], hdu: str, columns: list[str]) -> None:
    """Check the energy binning is identical in every seed (as girfs does)."""
    ref = seeds[0][hdu].data
    for seed in seeds[1:]:
        for col in columns:
            if not np.allclose(ref[col], seed[hdu].data[col]):
                raise ValueError(f"{hdu}.{col}: bins differ between seeds")


def merge(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Merge the 5 seeds as the published figures do: mean, min-max band."""
    if values.shape[0] != len(SEEDS):
        raise ValueError(f"expected {len(SEEDS)} seeds, got {values.shape[0]}")
    if np.isnan(values).any():
        raise ValueError("NaN in a kept bin; the published curve has no point there")
    mean = values.mean(axis=0)
    err_low, err_high = mean - values.min(axis=0), values.max(axis=0) - mean
    # the mean can sit a float round-off below the min; more than that is a bug
    tolerance = 1e-9 * np.abs(mean)
    if (err_low < -tolerance).any() or (err_high < -tolerance).any():
        raise ValueError("band edges on the wrong side of the mean")
    return mean, np.maximum(err_low, 0), np.maximum(err_high, 0)


def check_grid(low: np.ndarray, high: np.ndarray, name: str) -> None:
    """Check the binning: 5 bins per decade, plus under- and overflow bins."""
    if len(low) != 17:
        raise ValueError(f"{name}: expected 17 bins, got {len(low)}")
    if not np.isclose(low[1], 0.02) or not np.isclose(high[-2], 20.0):
        raise ValueError(f"{name}: not the 0.02-20 TeV range")
    if not np.allclose(np.log10(high[1:-2] / low[1:-2]), 0.2):
        raise ValueError(f"{name}: not 5 bins per decade")


def meta(
    quantity: str,
    definition: str,
    label: str,
    hdu: str,
    column: str,
    unit: str,
    cuts: str,
    notes: str,
) -> RecordMeta:
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=f"LST-1 {label}, gamma-PhysNet vanilla, clean simulations, zenith 20 deg",
        quantity=quantity,
        definition=definition,
        energy_type="true",
        instrument="lst1",
        configuration="mono",
        analysis="gphysnet",
        data_kind="monte_carlo",
        conditions={
            "zenith_range": ["20 deg", "20 deg"],
            "azimuth": "180 deg",
            "offset": "unknown",  # point-source gammas, position in the field of view not stated
            "moon": "dark",  # intrinsic night-sky background only, no added noise
            "analysis_details": ANALYSIS_DETAILS,
            "cuts": cuts,
        },
        provenance={
            "method": "official_data_file",
            "location": (
                "Supplementary repository of the paper, 'Comparison with lstchain' page "
                f"(irfs_vs_lstchain), drawn from these files; {ARCHIVE}: "
                f"irfs/vanilla/best_scenario/seed_0..4/irfs.fits.gz, HDU {hdu}"
            ),
            "original_column": f"{column} [{unit}], merged over the 5 seeds",
        },
        notes=notes,
    )


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Download the source into ``cache_dir`` and write every record into ``out``."""
    files = fetch(cache_dir)
    seeds = seed_tables(files)

    # ------------------------------------------------------------------ checks
    for hdu, columns in (
        ("ANGULAR_RESOLUTION", ["true_energy_low", "true_energy_high", "true_energy_center"]),
        ("ENERGY_BIAS_RESOLUTION", ["true_energy_low", "true_energy_high", "true_energy_center"]),
        ("GH_CUTS", ["true_energy_low", "true_energy_high"]),
    ):
        same_bins(seeds, hdu, columns)
    # the effective-area HDU is 2D; the bin edges are arrays inside one row
    ref = seeds[0]["EFFECTIVE_AREA"].data
    for seed in seeds[1:]:
        for col in ("ENERG_LO", "ENERG_HI"):
            if not np.allclose(ref[col][0], seed["EFFECTIVE_AREA"].data[col][0]):
                raise ValueError(f"EFFECTIVE_AREA.{col}: bins differ between seeds")
        if seed["EFFECTIVE_AREA"].data["EFFAREA"].shape != (1, 1, 17):
            raise ValueError("EFFECTIVE_AREA: unexpected shape")

    ang = seeds[0]["ANGULAR_RESOLUTION"].data
    check_grid(ang["true_energy_low"], ang["true_energy_high"], "ANGULAR_RESOLUTION")

    # the gammaness cut keeps exactly 70 % of the gamma rays of the
    # direction-cut sample in every bin: the paper's "top 70 % gammaness"
    for seed in seeds:
        area = seed["EFFECTIVE_AREA"].data["EFFAREA"][0]
        area_gh = seed["EFFECTIVE_AREA_ANG_RES"].data["EFFAREA"][0]
        ratio = area / area_gh
        if not np.allclose(ratio, 0.7, atol=0.01):
            raise ValueError(f"gammaness cut is not 70 %: {np.round(ratio, 3)}")

    # --------------------------------------------------------------- records
    # every published curve drops the under- and overflow bins
    lo = ang["true_energy_low"][1:-1]
    hi = ang["true_energy_high"][1:-1]
    center = ang["true_energy_center"][1:-1]
    bins = {"energy_min": lo * u.TeV, "energy_max": hi * u.TeV, "energy": center * u.TeV}
    n_bins = len(lo)
    if n_bins != 15:
        raise ValueError(f"expected 15 kept bins, got {n_bins}")

    seeds_err = (
        "The value is the mean over the 5 training seeds of the archive; the errors are "
        "the min-max band over the seeds, as in the published figures."
    )

    # angular resolution: 68 % containment, computed on the events passing
    # the gammaness cut (the paper's "top 70 % gammaness")
    values = np.array([s["ANGULAR_RESOLUTION"].data["angular_resolution"][1:-1] for s in seeds])
    value, err_low, err_high = merge(values)
    write_record(
        out / "angular_resolution_containment-68_zd20_gh70_gphysnet.ecsv",
        bins
        | {
            "value": value * u.deg,
            "value_err_low": err_low * u.deg,
            "value_err_high": err_high * u.deg,
        },
        meta(
            "angular_resolution",
            "containment_68",
            "angular resolution, 68 % containment of the gamma rays passing the gammaness cut",
            "ANGULAR_RESOLUTION",
            "angular_resolution",
            "deg",
            GH_CUT,
            seeds_err
            + " Unlike the lstchain curves it is compared with, wrong head-tail events are not "
            "removed (the comparison cannot do it), which the repository's comparison page "
            "points out.",
        ),
    )

    # energy resolution and bias from the same HDU
    for quantity, definition, column, label, fname in (
        ("energy_resolution", "containment_68", "resolution",
         "energy resolution, 68 % containment of |E_R - E_T|/E_T",
         "energy_resolution_containment-68"),
        ("energy_bias", "median", "bias", "energy bias, median of (E_R - E_T)/E_T",
         "energy_bias_median"),
    ):  # fmt: skip
        values = np.array([s["ENERGY_BIAS_RESOLUTION"].data[column][1:-1] for s in seeds])
        value, err_low, err_high = merge(values)
        write_record(
            out / f"{fname}_zd20_gh70_gphysnet.ecsv",
            bins
            | {
                "value": value * u.one,
                "value_err_low": err_low * u.one,
                "value_err_high": err_high * u.one,
            },
            meta(
                quantity, definition, label, "ENERGY_BIAS_RESOLUTION", column, "", GH_CUT, seeds_err
            ),
        )

    # effective area after the direction cut and the gammaness cut
    values = np.array([s["EFFECTIVE_AREA"].data["EFFAREA"][0][0][1:-1] for s in seeds])
    value, err_low, err_high = merge(values)
    area_lo = seeds[0]["EFFECTIVE_AREA"].data["ENERG_LO"][0][1:-1]
    area_hi = seeds[0]["EFFECTIVE_AREA"].data["ENERG_HI"][0][1:-1]
    if not (np.allclose(area_lo, lo) and np.allclose(area_hi, hi)):
        raise ValueError("effective-area bins differ from the resolution bins")
    write_record(
        out / "effective_area_direction-cut_zd20_gh70_gphysnet.ecsv",
        {
            "energy_min": area_lo * u.TeV,
            "energy_max": area_hi * u.TeV,
            "value": value * u.m**2,
            "value_err_low": err_low * u.m**2,
            "value_err_high": err_high * u.m**2,
        },
        meta(
            "effective_area",
            "direction_cut",
            "effective area, after the direction and gammaness cuts",
            "EFFECTIVE_AREA",
            "EFFAREA",
            "m2",
            GH_CUT + "; direction cut keeping 70 % of the gamma rays in each bin of true energy",
            seeds_err,
        ),
    )


if __name__ == "__main__":
    extract()

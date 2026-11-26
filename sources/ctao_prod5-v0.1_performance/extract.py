"""Official performance curves of the CTAO Prod5 v0.1 IRFs (Zenodo 10.5281/zenodo.5499840).

Reads the ROOT files of the full bundle in memory and writes one record per
histogram shown in the official figures, for every site, (sub-)array, zenith
angle and optimisation time, azimuth-averaged pointing.

    python sources/ctao_prod5-v0.1_performance/extract.py
"""

from __future__ import annotations

from pathlib import Path

from iact_perf.extract.eventdisplay import (
    DURATION_TAGS,
    DURATIONS,
    HISTOGRAMS,
    iter_release,
    read_curve,
    record_meta,
)
from iact_perf.extract.zenodo import download
from iact_perf.records import write_record

RECORD = 5499840
BUNDLE = "cta-prod5-zenodo-v0.1.zip"
HERE = Path(__file__).parent

# Prod5-North-20deg-AverageAz-4LSTs09MSTs.180000s-v0.1.root
PATTERN = (
    r"Prod5-(?P<site>North|South)-(?P<zenith>\d+)deg-(?P<azimuth>AverageAz)"
    r"-(?P<array>[0-9A-Za-z]+)\.(?P<duration>\d+)s-v0\.1\.root"
)
ARRAYS = {
    ("North", "4LSTs09MSTs"): ("north_alpha", "north", "CTAO-North Alpha"),
    ("North", "4LSTs"): ("north_alpha_lst", "north-lst", "CTAO-North Alpha LST sub-array"),
    ("North", "09MSTs"): ("north_alpha_mst", "north-mst", "CTAO-North Alpha MST sub-array"),
    ("South", "14MSTs37SSTs"): ("south_alpha", "south", "CTAO-South Alpha"),
    ("South", "14MSTs"): ("south_alpha_mst", "south-mst", "CTAO-South Alpha MST sub-array"),
    ("South", "37SSTs"): ("south_alpha_sst", "south-sst", "CTAO-South Alpha SST sub-array"),
}
#: ERes has no energy type on its axis; the archived release web page plots
#: the energy resolution "as a function of reconstructed energy".
ERES_ENERGY_TYPE = "reconstructed"

DETAILS = (
    "Eventdisplay analysis with BDT gamma/hadron separation (CTAO Prod5 v0.1), "
    "on-axis point-source gamma rays; CORSIKA 7.71 (QGSJet-II-04, URQMD), sim_telarray"
)
CUTS = "cuts optimised for point-source flux sensitivity in each energy bin, for {t}"


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    bundle = download(RECORD, BUNDLE, cache_dir)
    n = 0
    for fields, f in iter_release(bundle, PATTERN):
        config, tag, name = ARRAYS[(fields["site"], fields["array"])]
        duration = DURATIONS[fields["duration"]]
        zd = fields["zenith"]
        for h in HISTOGRAMS:
            curve = read_curve(f, h, ERES_ENERGY_TYPE)
            if curve is None:
                continue
            meta = record_meta(
                h,
                curve,
                label=f"{name}, Prod5 v0.1, {h.stem.replace('_', ' ')}, "
                f"zenith {zd} deg, cuts optimised for {duration}",
                configuration=config,
                analysis="prod5-official",
                zenith=f"{zd} deg",
                azimuth="average",
                moon="dark",
                duration=duration,
                analysis_details=DETAILS,
                cuts=CUTS.format(t=duration),
                location=f"{Path(f.name).name}, histogram {h.key}",
            )
            stem = f"{h.stem}_{tag}_zd{zd}_{DURATION_TAGS[fields['duration']]}"
            write_record(out / f"{stem}.ecsv", curve["columns"], meta)
            n += 1
    if n == 0:
        raise ValueError(f"no record written from {bundle}")


if __name__ == "__main__":
    extract()

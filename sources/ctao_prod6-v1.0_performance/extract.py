"""Official performance curves of the CTAO Prod6 v1.0 IRFs (Zenodo 10.5281/zenodo.22871179).

Reads the ROOT files of the full bundle in memory and writes one record per
histogram shown in the official figures, for every site, zenith angle, sky
condition and optimisation time, azimuth-averaged pointing.

    python sources/ctao_prod6-v1.0_performance/extract.py
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

RECORD = 22871179
BUNDLE = "ctao-prod6-zenodo-v1.0.zip"
HERE = Path(__file__).parent

# Prod6-CTAO-North-20deg-AverageAz-4LSTs09MSTs-dark-180000s-v1.0.root
PATTERN = (
    r"Prod6-CTAO-(?P<site>North|South)-(?P<zenith>\d+)deg-(?P<azimuth>AverageAz)"
    r"-(?P<array>[0-9A-Za-z]+)-(?P<sky>dark|halfmoon)-(?P<duration>\d+)s-v1\.0\.root"
)
ARRAYS = {
    ("North", "4LSTs09MSTs"): ("north_beta", "north", "CTAO-North Beta"),
    ("South", "2LSTs14MSTs37SSTs"): ("south_beta", "south", "CTAO-South Beta"),
}
#: Moon field of the records; the README defines half moon as an average sky
#: brightness five times the dark-sky level.
MOON = {"dark": "dark", "halfmoon": "moderate"}
#: ERes has no energy type on its axis; the official Prod6 energy resolution
#: figure plots it against "True gamma-ray energy E_T".
ERES_ENERGY_TYPE = "true"

DETAILS = (
    "Eventdisplay v5.17.0 with Eventdisplay-ML v1.0.0 stereo reconstruction "
    "(CTAO Prod6 v1.0), on-axis point-source gamma rays; CORSIKA 7.750 "
    "(QGSJET-II-04, URQMD), sim_telarray 2024.36.1"
)
SKY = {"dark": "dark sky", "halfmoon": "half moon (5x the dark-sky NSB level)"}
CUTS = "cuts optimised for point-source flux sensitivity in each energy bin, for {t}; {sky}"


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    bundle = download(RECORD, BUNDLE, cache_dir)
    n = 0
    for fields, f in iter_release(bundle, PATTERN):
        config, tag, name = ARRAYS[(fields["site"], fields["array"])]
        duration = DURATIONS[fields["duration"]]
        zd, sky = fields["zenith"], fields["sky"]
        for h in HISTOGRAMS:
            curve = read_curve(f, h, ERES_ENERGY_TYPE)
            if curve is None:
                continue
            meta = record_meta(
                h,
                curve,
                label=f"{name}, Prod6 v1.0, {h.stem.replace('_', ' ')}, zenith {zd} deg, "
                f"{SKY[sky].split(' (')[0]}, cuts optimised for {duration}",
                configuration=config,
                analysis="prod6-official",
                zenith=f"{zd} deg",
                azimuth="average",
                moon=MOON[sky],
                duration=duration,
                analysis_details=DETAILS,
                cuts=CUTS.format(t=duration, sky=SKY[sky]),
                location=f"{Path(f.name).name}, histogram {h.key}",
            )
            stem = f"{h.stem}_{tag}_zd{zd}_{sky}_{DURATION_TAGS[fields['duration']]}"
            write_record(out / f"{stem}.ecsv", curve["columns"], meta)
            n += 1
    if n == 0:
        raise ValueError(f"no record written from {bundle}")


if __name__ == "__main__":
    extract()

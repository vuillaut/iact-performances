"""Extract the appendix tables of Aleksić et al. 2016 (MAGIC performance after the upgrade).

Reads the LaTeX source of arXiv:1409.5594 and writes one ECSV record per
quantity, definition and zenith range. Run from anywhere:

    python sources/magic_aleksic2016_performance-upgrade/extract.py
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u

from iact_perf.extract.arxiv import get_tex
from iact_perf.extract.latex import find_table, parse_cell, parse_range, split_rows
from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

ARXIV = "1409.5594"
HERE = Path(__file__).parent

ZENITH = {
    "zd00-30": ["0 deg", "30 deg"],
    "zd30-45": ["30 deg", "45 deg"],
}
TABLE_NAME = {
    "tab:enreslz": "Table A.2",
    "tab:enresmz": "Table A.3",
    "tab:angres": "Table A.4",
    "tab:intsens": "Table A.5",
    "tab:intsens2": "Table A.6",
    "tab:diffsens": "Table A.7",
    "tab:diffsens2": "Table A.8",
}

PERCENT_CU = u.percent * u.Unit("CU")


def meta(label, quantity, zd, tab, column, *, conditions=None, **kw) -> RecordMeta:
    cond = {"zenith_range": ZENITH[zd], "analysis_details": "MARS (standard MAGIC analysis)"}
    cond.update(conditions or {})
    return RecordMeta(
        schema_version=SCHEMA_VERSION,
        label=label,
        quantity=quantity,
        instrument="magic",
        configuration="stereo_upgraded",
        analysis="magic-mars-standard",
        conditions=cond,
        provenance={
            "method": "latex_table",
            "location": f"{TABLE_NAME[tab]} ({tab})",
            "original_column": column,
        },
        **kw,
    )


def cells(tab, tex):
    """Data rows of a table: the rows after the header (the paper ends it with a double hline)."""
    body = find_table(tex, tab)
    header, data = body.split(r"\hline\hline", 1)
    return split_rows(data)


def column(rows, i):
    parsed = [parse_cell(r[i]) for r in rows]
    out = {"value": [c.value for c in parsed]}
    if all(c.err_low is not None for c in parsed):
        out["value_err_low"] = [c.err_low for c in parsed]
        out["value_err_high"] = [c.err_high for c in parsed]
    return out


def with_unit(col, unit):
    return {k: v * unit for k, v in col.items()}


def energy_resolution(tex, out):
    """Tables A.2/A.3: MC, bins of true energy (5 per decade)."""
    for tab, zd in (("tab:enreslz", "zd00-30"), ("tab:enresmz", "zd30-45")):
        rows = cells(tab, tex)
        lo, hi = (list(x) for x in zip(*(parse_range(r[0]) for r in rows), strict=True))
        energy = {"energy_min": lo * u.GeV, "energy_max": hi * u.GeV}
        common = dict(data_kind="monte_carlo", energy_type="true")
        specs = [
            ("energy_bias", "gaussian_mean", 1, "bias [%]", "Energy bias, mean of a Gaussian fit"),
            ("energy_resolution", "gaussian_sigma", 2, "sigma [%]", "Energy resolution, sigma of a Gaussian fit"),
            ("energy_resolution", "rms", 3, "RMS [%]", "Energy resolution, RMS of the distribution"),
        ]  # fmt: skip
        for quantity, definition, i, colname, label in specs:
            m = meta(
                f"MAGIC stereo, {label} of (E_est - E_true)/E_true, {zd}",
                quantity,
                zd,
                tab,
                colname,
                definition=definition,
                **common,
            )
            name = f"{quantity}_{definition.replace('_', '-')}_{zd}.ecsv"
            write_record(out / name, energy | with_unit(column(rows, i), u.percent), m)


def angular_resolution(tex, out):
    """Table A.4: Crab data, points in estimated energy, both zenith ranges side by side."""
    tab = "tab:angres"
    rows = cells(tab, tex)
    energy = {"energy": [parse_cell(r[0]).value for r in rows] * u.GeV}
    specs = [
        ("zd00-30", 1, "gaussian_sigma", "Theta_Gaus, zenith < 30 deg", "sigma of a 2D Gaussian fit"),
        ("zd00-30", 2, "containment_68", "Theta_0.68, zenith < 30 deg", "68% containment radius"),
        ("zd30-45", 3, "gaussian_sigma", "Theta_Gaus, zenith 30-45 deg", "sigma of a 2D Gaussian fit"),
        ("zd30-45", 4, "containment_68", "Theta_0.68, zenith 30-45 deg", "68% containment radius"),
    ]  # fmt: skip
    for zd, i, definition, colname, label in specs:
        m = meta(
            f"MAGIC stereo angular resolution, {label} of the Crab excess, {zd}",
            "angular_resolution",
            zd,
            tab,
            colname,
            definition=definition,
            data_kind="real_data",
            energy_type="reconstructed",
            conditions={"offset": "0.4 deg"},
        )
        name = f"angular_resolution_{definition.replace('_', '-')}_{zd}.ecsv"
        write_record(out / name, energy | with_unit(column(rows, i), u.deg), m)


def sensitivity(tex, out):
    """Tables A.5-A.8: integral (above threshold) and differential (5 bins/decade)."""
    tables = [
        ("tab:intsens", "zd00-30", "integral"),
        ("tab:intsens2", "zd30-45", "integral"),
        ("tab:diffsens", "zd00-30", "differential"),
        ("tab:diffsens2", "zd30-45", "differential"),
    ]
    for tab, zd, integration in tables:
        rows = cells(tab, tex)
        if integration == "integral":
            # The threshold is the peak of the true energy distribution of MC events
            energy = {"energy": [parse_cell(r[0]).value for r in rows] * u.GeV}
            energy_type = "true"
            first = 1
            flux_unit = u.Unit("1e-13 cm-2 s-1")
        else:
            lo = [parse_cell(r[0]).value for r in rows]
            hi = [parse_cell(r[1]).value for r in rows]
            energy = {"energy_min": lo * u.GeV, "energy_max": hi * u.GeV}
            energy_type = "reconstructed"
            first = 2
            flux_unit = u.Unit("1e-12 cm-2 s-1 TeV-1")

        common = dict(
            data_kind="real_data",
            energy_integration=integration,
            energy_type=energy_type,
            conditions={"offset": "0.4 deg"},
        )
        # Rates of Crab gamma rays and residual background after the sensitivity cuts
        for k, (quantity, colname, what) in enumerate(
            [("gamma_rate", "gamma-rate", "Crab gamma-ray rate"),
             ("background_rate", "bkg-rate", "residual background rate")]
        ):  # fmt: skip
            m = meta(
                f"MAGIC stereo {integration} {what} after sensitivity cuts, {zd}",
                quantity,
                zd,
                tab,
                f"{colname} [min-1]",
                **common,
            )
            name = f"{quantity}_{integration}_{zd}.ecsv"
            write_record(out / name, energy | with_unit(column(rows, first + k), 1 / u.min), m)

        criteria = dict(
            significance=5,
            min_excess=10,
            min_signal_to_background=0.05,
            bins_per_decade=5 if integration == "differential" else None,
        )
        sens = [
            ("excess-over-sqrt-bkg", "excess_over_sqrt_background", None, "S_Nex/sqrt(Nbkg) [%C.U.]", PERCENT_CU),
            ("li-ma-1off", "li_ma_eq17", 1, "S_Li&Ma,1Off [%C.U.]", PERCENT_CU),
            ("li-ma-3off", "li_ma_eq17", 3, "S_Li&Ma,3Off [%C.U.]", PERCENT_CU),
            ("li-ma-5off", "li_ma_eq17", 5, "S_Li&Ma,5Off [%C.U.]", PERCENT_CU),
            ("excess-over-sqrt-bkg", "excess_over_sqrt_background", None, f"S_Nex/sqrt(Nbkg) [{flux_unit}]", flux_unit),
        ]  # fmt: skip
        for j, (tag, formula, n_off, colname, unit) in enumerate(sens):
            in_cu = unit is PERCENT_CU
            m = meta(
                f"MAGIC stereo {integration} sensitivity, 50 h, {tag}, "
                f"{'Crab units' if in_cu else 'flux'}, {zd}",
                "sensitivity",
                zd,
                tab,
                colname,
                observation_time="50 h",
                sensitivity_criteria=criteria | {"significance_formula": formula, "n_off_regions": n_off},
                crab_reference="magic_aleksic2016" if in_cu else None,
                **common,
            )  # fmt: skip
            name = f"sensitivity_{integration}_{tag}_{'crab' if in_cu else 'flux'}_{zd}.ecsv"
            write_record(out / name, energy | with_unit(column(rows, first + 2 + j), unit), m)


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    tex = get_tex(ARXIV, "mup.tex", cache_dir)
    energy_resolution(tex, out)
    angular_resolution(tex, out)
    sensitivity(tex, out)


if __name__ == "__main__":
    extract()

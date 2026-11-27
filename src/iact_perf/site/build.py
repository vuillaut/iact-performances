"""Generate the Zensical project of the website from the database.

``build(root, out)`` writes ``out/zensical.toml`` and ``out/docs/``: a home page,
the comparison page, one page per source and per instrument, the analyses,
the design and contribution docs, the JSON export and the record files. Then
``zensical build -f out/zensical.toml`` makes the static site in ``out/site/``.
"""

from __future__ import annotations

import shutil
from collections import Counter
from importlib import resources
from pathlib import Path

from ..catalog import default_root
from ..database import Database, load
from .export import QUANTITY_NAMES, export

#: Curves selected when the comparison page opens without a shared link.
DEFAULT_CURVES = [
    "ctao_prod6-v1.0_performance/sensitivity_differential_south_zd20_dark_50h",
    "ctao_prod6-v1.0_performance/sensitivity_differential_north_zd20_dark_50h",
    "ctao_prod5-v0.1_performance/sensitivity_differential_south_zd20_50h",
    "ctao_prod5-v0.1_performance/sensitivity_differential_north_zd20_50h",
    "magic_aleksic2016_performance-upgrade/sensitivity_differential_excess-over-sqrt-bkg_flux_zd00-30",
]

PLOTLY = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def _cell(text) -> str:
    """Text safe for a markdown table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def _source_link(src) -> str:
    if src.doi:
        return f"[doi:{src.doi}](https://doi.org/{src.doi})"
    return f"[{src.url}]({src.url}) (accessed {src.accessed})"


def _authors(src) -> str:
    a = src.authors
    return (
        a[0]
        if len(a) == 1
        else (f"{a[0]} et al." if a[-1] == "et al." or len(a) > 3 else ", ".join(a))
    )


def build(root: Path | None = None, out: Path = Path("build/site"), repo_url: str | None = None):
    root = Path(root) if root else default_root()
    out = Path(out)
    docs = out / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    docs.mkdir(parents=True)
    db = load(root)

    summary = export(db, docs / "data" / "records.json")
    assets = resources.files("iact_perf.site") / "assets"
    for name in ("compare.js", "compare.css"):
        (docs / "assets").mkdir(exist_ok=True)
        (docs / "assets" / name).write_text((assets / name).read_text())

    (docs / "index.md").write_text(_home(db))
    (docs / "compare.md").write_text(_compare())
    _sources(db, root, docs)
    _instruments(db, docs)
    (docs / "analyses.md").write_text(_analyses(db))
    (docs / "about").mkdir()
    for name, target in (("docs/design.md", "design.md"), ("AGENTS.md", "contributing.md")):
        src = root / name
        if src.exists():
            (docs / "about" / target).write_text(src.read_text())

    (out / "zensical.toml").write_text(_zensical_toml(db, repo_url))
    return summary


# --------------------------------------------------------------------------- pages


def _home(db: Database) -> str:
    counts = Counter((r.meta.instrument, r.meta.quantity) for r in db.records)
    quantities = sorted({q for _, q in counts}, key=list(QUANTITY_NAMES).index)
    rows = [
        [f"[{db.instruments[i].name}](instruments/{i}.md)"]
        + [counts.get((i, q), "") for q in quantities]
        for i in sorted(db.instruments)
    ]
    return f"""# Cherenkov telescope performances

A community database of **published** performances of Cherenkov telescopes:
sensitivity, angular and energy resolution, effective area, background rates.
Every value comes from a publication or an official data release, with the
conditions it was obtained under and where it was taken from.

[Compare curves](compare.md){{ .md-button .md-button--primary }}
[Browse the sources](sources/index.md){{ .md-button }}

**{len(db.records)} records** from **{len(db.sources)} sources**, {len(db.instruments)} instruments,
{len(db.analyses)} analyses.

{_table(["Instrument"] + [QUANTITY_NAMES[q].capitalize() for q in quantities], rows)}
## Use the data

```bash
pip install iact-perf
```

```python
import iact_perf

db = iact_perf.load()
recs = db.query(instrument="ctao", analysis="prod6-official", quantity="sensitivity",
                zenith="20 deg", observation_time="50 h")
recs[0].table  # astropy QTable, values as published
```

Each source page links its records as ECSV files.

## Cite

Cite the original source of every value you use (given on its source page),
and this database. Data: CC-BY-4.0. Code: BSD-3-Clause.

!!! warning "Compare with care"
    Curves from different sources are not always comparable: sensitivity
    criteria, observation times, cuts, zenith ranges and energy definitions
    differ. The comparison page shows these conditions for every curve.
"""


def _compare() -> str:
    import json

    defaults = json.dumps(DEFAULT_CURVES).replace('"', "&quot;")
    return f"""---
hide:
  - navigation
  - toc
---

# Compare performance curves

Choose a quantity, narrow the list with the filters, tick up to eight curves.
The link in the address bar keeps your selection. Differential sensitivities
are shown as E² dN/dE; values published in Crab units are converted with the
Crab spectrum of their source (noted under the plot).

<div id="iact-compare" data-src="../data/records.json" data-defaults="{defaults}">
  <div class="ic-filters"></div>
  <p class="ic-loading">Loading…</p>
  <div class="ic-plot"></div>
  <div class="ic-list"></div>
  <div class="ic-details"></div>
</div>

<script src="{PLOTLY}" charset="utf-8"></script>
"""


def _sources(db: Database, root: Path, docs: Path) -> None:
    folder = docs / "sources"
    folder.mkdir()
    rows = []
    by_source: dict[str, list] = {}
    for r in db.records:
        by_source.setdefault(r.source, []).append(r)
    for slug, src in sorted(db.sources.items(), key=lambda kv: (-kv[1].year, kv[0])):
        recs = by_source.get(slug, [])
        rows.append(
            [f"[{src.title}]({slug}.md)", _authors(src), src.year, src.source_type,
             ", ".join(src.instruments), len(recs)]
        )  # fmt: skip
        data_dir = docs / "data" / "sources" / slug
        data_dir.mkdir(parents=True)
        for p in sorted((root / "sources" / slug).glob("*.ecsv")):
            shutil.copy2(p, data_dir / p.name)
        (folder / f"{slug}.md").write_text(_source_page(db, slug, src, recs))
    (folder / "index.md").write_text(
        "# Sources\n\n"
        + _table(["Title", "Authors", "Year", "Type", "Instruments", "Records"], rows)
    )


def _source_page(db, slug, src, recs) -> str:
    lines = [f"# {src.title}\n", f"{', '.join(src.authors)} ({src.year}). {_source_link(src)}\n"]
    facts = [
        ["Type", src.source_type + (" (refereed)" if src.refereed else "")],
        ["Instruments", ", ".join(f"[{i}](../instruments/{i}.md)" for i in src.instruments)],
        ["Identifier in the database", f"`{slug}`"],
    ]
    if src.arxiv:
        facts.append(["arXiv", f"[{src.arxiv}](https://arxiv.org/abs/{src.arxiv})"])
    if src.ads_bibcode:
        facts.append(
            ["ADS", f"[{src.ads_bibcode}](https://ui.adsabs.harvard.edu/abs/{src.ads_bibcode})"]
        )
    if src.superseded_by:
        facts.append(["Superseded by", f"[{src.superseded_by}]({src.superseded_by}.md)"])
    lines.append(_table(["", ""], facts))
    if src.notes:
        lines.append(f"## Notes\n\n{src.notes}\n")
    lines.append(f"## Records ({len(recs)})\n")
    rows = []
    for r in sorted(recs, key=lambda r: r.id):
        m = r.meta
        zr = m.conditions.zenith_range
        rows.append(
            [
                f"[{r.id}](../data/sources/{slug}/{r.id}.ecsv)",
                m.quantity + (f" ({m.energy_integration})" if m.energy_integration else ""),
                m.definition or "",
                m.configuration,
                m.analysis,
                zr if isinstance(zr, str) else "–".join(z.replace(" deg", "") for z in zr) + "°",
                m.observation_time or "",
                m.conditions.moon,
                len(r.table),
            ]
        )
    lines.append(
        _table(["Record (ECSV)", "Quantity", "Definition", "Configuration", "Analysis",
                "Zenith", "Time", "Moon", "Points"], rows)
    )  # fmt: skip
    return "\n".join(lines)


def _instruments(db: Database, docs: Path) -> None:
    folder = docs / "instruments"
    folder.mkdir()
    for inst in db.instruments.values():
        srcs = [s for s, src in db.sources.items() if inst.id in src.instruments]
        n = Counter(r.meta.configuration for r in db.records if r.meta.instrument == inst.id)
        page = [f"# {inst.name}\n", f"Type: {inst.type}\n"]
        if inst.site:
            page.append(f"Site: {inst.site.name}\n")
        if inst.notes:
            page.append(inst.notes + "\n")
        page.append("## Configurations\n")
        page.append(
            _table(["Id", "Description", "Mode", "Telescopes", "Period", "Records"],
                   [[f"`{c.id}`", c.description, c.mode, c.n_telescopes or "",
                     "–".join(p for p in (c.period_start, c.period_end) if p) or "", n.get(c.id, 0)]
                    for c in inst.configurations])
        )  # fmt: skip
        page.append("## Sources\n")
        page += [
            f"- [{db.sources[s].title}](../sources/{s}.md) ({db.sources[s].year})" for s in srcs
        ]
        (folder / f"{inst.id}.md").write_text("\n".join(page) + "\n")


def _analyses(db: Database) -> str:
    n = Counter(r.meta.analysis for r in db.records)
    rows = [[f"`{a.id}`", a.name, a.description, n.get(a.id, 0)] for a in db.analyses.values()]
    return (
        "# Analyses\n\nEvery record names the analysis chain or production that made it. "
        "Query them with `db.query(analysis=...)`.\n\n"
        + _table(["Id", "Name", "Description", "Records"], rows)
    )


def _nav_name(db: Database, slug: str) -> str:
    """Short navigation label from the slug: 'MAGIC aleksic2016 performance-upgrade'."""
    inst, who, topic = slug.split("_")
    name = db.instruments[inst].name if inst in db.instruments else inst
    return f"{name} {who} {topic}"


def _zensical_toml(db: Database, repo_url: str | None) -> str:
    import tomli_w

    sources = sorted(db.sources.items(), key=lambda kv: (-kv[1].year, kv[0]))
    project = {
        "site_name": "Cherenkov telescope performances",
        "site_description": "A database of published Cherenkov telescope performances",
        "docs_dir": "docs",
        "site_dir": "site",
        "extra_css": ["assets/compare.css"],
        # declared here, not in compare.md: Zensical resolves these paths against
        # the site root, while a <script src> in Markdown is not reliably rewritten
        # (it broke the page when served under /iact-performances/)
        "extra_javascript": ["assets/compare.js"],
        "nav": [
            {"Home": "index.md"},
            {"Compare": "compare.md"},
            {"Sources": [{"All sources": "sources/index.md"}]
             + [{_nav_name(db, slug): f"sources/{slug}.md"} for slug, _ in sources]},
            {"Instruments": [{db.instruments[i].name: f"instruments/{i}.md"}
                             for i in sorted(db.instruments)]},
            {"Analyses": "analyses.md"},
            {"About": [{"Design": "about/design.md"}, {"Contributing": "about/contributing.md"}]},
        ],
        # no navigation.instant: the comparison page runs its own scripts on load
        "theme": {
            "language": "en",
            "features": ["navigation.sections", "navigation.top", "navigation.footer",
                         "content.code.copy", "search.highlight"],
            "palette": [
                {"media": "(prefers-color-scheme: light)", "scheme": "default",
                 "toggle": {"icon": "lucide/moon", "name": "Switch to dark mode"}},
                {"media": "(prefers-color-scheme: dark)", "scheme": "slate",
                 "toggle": {"icon": "lucide/sun", "name": "Switch to light mode"}},
            ],
        },
        "markdown_extensions": {
            "admonition": {}, "attr_list": {}, "md_in_html": {}, "tables": {},
            "toc": {"permalink": True}, "pymdownx.details": {}, "pymdownx.superfences": {},
        },
    }  # fmt: skip
    if repo_url:
        project["repo_url"] = repo_url
    return tomli_w.dumps({"project": project})

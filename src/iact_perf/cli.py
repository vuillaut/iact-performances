"""The ``iact-perf`` command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import default_root, load_source, source_dirs, validate_repository
from .schema import SCHEMA_VERSION, SLUG_RE, write_json_schemas

SOURCE_TEMPLATE = """\
schema_version: "{schema_version}"
title: TODO full title
authors: ["TODO Lastname, F.", "et al."]
year: TODO
doi: TODO 10.xxxx/...       # publisher DOI; remove and set url + accessed if there is none
# url: https://...
# accessed: YYYY-MM-DD
arxiv: "TODO or remove"
ads_bibcode: TODO or remove
source_type: TODO article | proceedings | irf_release | webpage | thesis | report
refereed: TODO true | false
instruments: [{instrument}]
reproducible: true
notes: >-
  TODO where the values come from (tables, figures, files) and anything a
  reader must know to use them.
"""

EXTRACT_TEMPLATE = '''\
"""Extract the records of {slug}.

    python sources/{slug}/extract.py
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u

from iact_perf.records import write_record
from iact_perf.schema import SCHEMA_VERSION, RecordMeta

HERE = Path(__file__).parent


def extract(out: Path = HERE, cache_dir: Path | None = None) -> None:
    """Download the source into ``cache_dir`` and write every record into ``out``."""
    raise NotImplementedError


if __name__ == "__main__":
    extract()
'''


def cmd_validate(args) -> int:
    errors = validate_repository(args.root)
    for e in errors:
        print(e)
    n = len(source_dirs(args.root or default_root()))
    print(f"{len(errors)} problem(s) in {n} source(s)" if errors else f"OK: {n} source(s) valid")
    return 1 if errors else 0


def cmd_reproduce(args) -> int:
    from .reproduce import reproduce

    root = args.root or default_root()
    slugs = args.slugs or [p.name for p in source_dirs(root) if load_source(p).source.reproducible]
    if not slugs:
        print("nothing to reproduce: give slugs or use --all")
        return 1
    failed = 0
    for slug in slugs:
        try:
            result = reproduce(slug, root, args.cache_dir, update=args.update)
        except Exception as err:
            print(f"{slug}: ERROR {type(err).__name__}: {err}")
            failed += 1
            continue
        print(result.report())
        failed += not result.ok
    if args.update and failed:
        print("--update: produced records written; review them with git diff")
    return 1 if failed and not args.update else 0


def cmd_list(args) -> int:
    from .database import load

    db = load(args.root)
    filters = {
        k: getattr(args, k)
        for k in ("quantity", "instrument", "analysis", "energy_integration")
        if getattr(args, k)
    }
    recs = db.query(source=args.source, include_superseded=True, **filters)
    table = db.summary(recs)
    if len(table):
        table.pprint_all() if args.all else table.pprint(max_width=-1)
    print(f"{len(recs)} record(s)")
    return 0


def cmd_new(args) -> int:
    root = args.root or default_root()
    if not SLUG_RE.match(args.slug):
        print(f"{args.slug!r} is not a valid slug: <instrument>_<firstauthor><year>_<topic>")
        return 1
    path = root / "sources" / args.slug
    if path.exists():
        print(f"{path} already exists")
        return 1
    instrument = args.slug.split("_")[0]
    path.mkdir(parents=True)
    (path / "source.yaml").write_text(
        SOURCE_TEMPLATE.format(schema_version=SCHEMA_VERSION, instrument=instrument)
    )
    (path / "extract.py").write_text(EXTRACT_TEMPLATE.format(slug=args.slug))
    print(f"created {path}/source.yaml and extract.py")
    if not (root / "instruments" / f"{instrument}.yaml").exists():
        print(f"note: instruments/{instrument}.yaml does not exist yet, add it")
    return 0


def cmd_site(args) -> int:
    import subprocess

    from .site.build import build

    summary = build(args.root, args.out, args.repo_url)
    print(f"{args.out}: {summary['records']} records in {summary['groups']} groups")
    for s in summary["skipped"]:
        print(f"  not exported: {s}")
    if args.build or args.serve:
        cmd = [
            "zensical",
            "serve" if args.serve else "build",
            "-f",
            str(args.out / "zensical.toml"),
        ]
        if args.build:
            cmd += ["--clean", "--strict"]
        return subprocess.call(cmd)
    return 0


def cmd_export_schema(args) -> int:
    for p in write_json_schemas((args.root or default_root()) / "schema"):
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iact-perf", description=__doc__)
    parser.add_argument("--root", type=Path, help="database root (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check every database file")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("reproduce", help="re-run extract.py and compare with committed records")
    p.add_argument("slugs", nargs="*", help="sources to reproduce (default: all reproducible)")
    p.add_argument("--cache-dir", type=Path, help="download cache (default: <root>/.cache)")
    p.add_argument(
        "--update", action="store_true", help="write the produced records into the source"
    )
    p.set_defaults(func=cmd_reproduce)

    p = sub.add_parser("list", help="list records")
    p.add_argument("--source")
    p.add_argument("--quantity")
    p.add_argument("--instrument")
    p.add_argument("--analysis")
    p.add_argument("--energy-integration", dest="energy_integration")
    p.add_argument("--all", action="store_true", help="print every row")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("new", help="create a source directory from templates")
    p.add_argument("slug")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("site", help="generate the website (Zensical project)")
    p.add_argument("--out", type=Path, default=Path("build/site"))
    p.add_argument("--repo-url", help="GitHub URL shown on the site")
    p.add_argument("--build", action="store_true", help="also run zensical build (strict)")
    p.add_argument("--serve", action="store_true", help="also run zensical serve")
    p.set_defaults(func=cmd_site)

    p = sub.add_parser("export-schema", help="regenerate schema/*.schema.json")
    p.set_defaults(func=cmd_export_schema)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""`atlas site build|preview|data` and `atlas x charts`.

`site build` and `site preview` drive the Observable Framework site. `site data`
builds the real site tables from saved runs (no Jev calls). `x charts` renders
the X-ready PNG charts from a site data directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from datetime import UTC, datetime


def _env(args) -> dict:
    env = dict(os.environ)
    if getattr(args, "data", None):
        env["ATLAS_SITE_DATA"] = args.data
    if getattr(args, "production", False):
        env["ATLAS_SITE_MODE"] = "production"
    if getattr(args, "base", None):
        env["ATLAS_SITE_BASE"] = args.base
    return env


def _build(args) -> None:
    from atlas import paths
    from atlas.sitedata.source import clear_cache

    clear_cache(paths.ROOT / "site")
    subprocess.run(
        ["npm", "run", "build"],
        cwd=paths.ROOT / "site",
        env=_env(args),
        check=True,
    )


def _preview(args) -> None:
    from atlas import paths
    from atlas.sitedata.source import clear_cache

    clear_cache(paths.ROOT / "site")
    subprocess.run(
        ["npm", "run", "dev"],
        cwd=paths.ROOT / "site",
        env=_env(args),
        check=True,
    )


def _default_snapshot() -> str:
    from atlas import paths

    with (paths.CONFIGS / "acquisition.toml").open("rb") as f:
        return tomllib.load(f)["snapshot_id"]


def _data(args) -> None:
    from atlas import paths
    from atlas.sitedata.build import build_site_data

    counts = build_site_data(
        args.out or paths.ROOT / "site" / "data-real",
        args.snapshot or _default_snapshot(),
        args.screen_run,
        args.facets_run,
        args.assign_run,
        args.taxonomy,
        args.label_set,
        benchmark_run=args.benchmark_run,
        facets_set=args.facets_set,
        cardset=args.cardset,
        facet_sample=args.facet_sample,
        replies_run=args.replies_run,
        top_n=args.top_n,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    print(json.dumps(counts, sort_keys=True))


def _charts(args) -> None:
    from atlas import paths
    from atlas.sitedata.xcharts import render_site_charts

    data = args.data or paths.ROOT / "site" / "data-real"
    out = args.out or paths.EXPORTS / "x" / datetime.now(UTC).date().isoformat()
    for path in render_site_charts(data, out):
        print(path)


def _register_data(ssub) -> None:
    d = ssub.add_parser("data", help="Build real site tables from saved runs")
    d.add_argument("--out", help="Output directory (default site/data-real)")
    d.add_argument("--snapshot", help="Snapshot id (default: acquisition.toml)")
    d.add_argument("--screen-run", required=True)
    d.add_argument("--facets-run", required=True)
    d.add_argument("--assign-run", required=True)
    d.add_argument("--taxonomy", required=True, help="Taxonomy version, e.g. t1")
    d.add_argument(
        "--label-set",
        action="append",
        default=[],
        help="Gold label set for PPI and quality rows (repeatable)",
    )
    d.add_argument("--benchmark-run", help="Synthetic benchmark run id")
    d.add_argument("--cardset", help="Cardset name (default: the only one)")
    d.add_argument(
        "--facet-sample",
        required=True,
        help="Phase-2 facet sample id (weights w1/p2, pos and neg phases)",
    )
    d.add_argument(
        "--replies-run",
        help="Run id with replies/unsolved_by_problem.parquet for unsolved_rate",
    )
    d.add_argument("--facets-set", default="facets@2")
    d.add_argument("--top-n", type=int, default=20)
    d.add_argument("--n-boot", type=int, default=2000)
    d.add_argument("--seed", type=int, default=0)
    d.set_defaults(func=_data)


def _register_x(sub) -> None:
    x = sub.add_parser("x", help="X-ready chart exports")
    xsub = x.add_subparsers(dest="x_cmd", required=True)
    c = xsub.add_parser("charts", help="Render 1600x900 PNG charts")
    c.add_argument("--data", help="Site data directory (default site/data-real)")
    c.add_argument("--out", help="Output directory (default exports/x/<date>)")
    c.set_defaults(func=_charts)


def register(sub) -> None:
    s = sub.add_parser("site", help="Build or preview the static atlas site")
    ssub = s.add_subparsers(dest="site_cmd", required=True)
    b = ssub.add_parser("build", help="Build the site into site/dist")
    b.add_argument("--data", help="Directory of exported site tables (parquet)")
    b.add_argument(
        "--production",
        action="store_true",
        help="Require --data with meta.mode == real",
    )
    b.add_argument("--base", help="URL base path, e.g. /jev-opportunity-atlas/")
    b.set_defaults(func=_build)
    p = ssub.add_parser("preview", help="Run the Observable Framework dev server")
    p.add_argument("--data", help="Directory of exported site tables (parquet)")
    p.add_argument("--base", help="URL base path, e.g. /jev-opportunity-atlas/")
    p.set_defaults(func=_preview)
    _register_data(ssub)
    _register_x(sub)

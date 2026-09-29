"""`atlas site build` and `atlas site preview`: the Observable Framework site."""

from __future__ import annotations

import os
import subprocess


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

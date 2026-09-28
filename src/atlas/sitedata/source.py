"""Loader-side data resolution for the Observable Framework site.

ATLAS_SITE_DATA points at a directory of exported parquet site tables; when it is
unset, loaders emit in-memory synthetic fixtures (meta.mode == "fixture"). A
production build (ATLAS_SITE_MODE=production) refuses anything but real data.
"""

from __future__ import annotations

import shutil
import sys
from os import environ
from pathlib import Path

import pyarrow.parquet as pq

from atlas import paths

_CACHE_KEEP = ("_npm", "_node", "_jsr")


class SiteModeError(RuntimeError):
    pass


def _meta_mode(dir: Path) -> str | None:
    try:
        meta = pq.read_table(dir / "meta.parquet").to_pydict()
    except FileNotFoundError:
        return None
    return dict(zip(meta["key"], meta["value"])).get("mode")


def resolve() -> Path | None:
    data = environ.get("ATLAS_SITE_DATA")
    production = environ.get("ATLAS_SITE_MODE") == "production"
    if data:
        dir = Path(data)
        if production and _meta_mode(dir) != "real":
            raise SiteModeError(
                f"production build needs meta.mode == real, not {dir}"
            )
        return dir
    if production:
        raise SiteModeError(
            "production build needs ATLAS_SITE_DATA with meta.mode == real"
        )
    return None


def emit(name: str, out=None) -> None:
    src = resolve()
    if src is None:
        # In-memory fixtures: loaders run concurrently, so never write
        # site/fixtures from here (they would race).
        from atlas.sitedata.fixtures import fixture_tables

        table = fixture_tables(0)[name]
    else:
        table = pq.read_table(src / f"{name}.parquet")
    pq.write_table(table, out if out is not None else sys.stdout.buffer)


def clear_cache(site_dir: Path) -> None:
    cache = site_dir / "src" / ".observablehq" / "cache"
    if not cache.is_dir():
        return
    for child in cache.iterdir():
        # Keep _npm/_node/_jsr: they hold dependency downloads (DuckDB-WASM
        # among them); clearing them would re-download on every build.
        if child.name in _CACHE_KEEP:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] != ["prebuild"]:
        print("usage: python -m atlas.sitedata.source prebuild", file=sys.stderr)
        return 2
    clear_cache(paths.ROOT / "site")
    try:
        resolve()
    except SiteModeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

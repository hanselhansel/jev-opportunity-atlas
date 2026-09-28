"""`atlas snapshot build` and `atlas snapshot verify`."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def _load_cfg(args):
    from atlas import paths
    from atlas.sources.acquire import load_config

    return load_config(paths.ROOT / args.config)


def _fetch_fn(cfg, scan_first: int, scan_last: int):
    from atlas.sources import context, hn_api

    def go(missing: set[int], out_dir: Path):
        async def run():
            async with hn_api.make_client(
                cfg["concurrency"], cfg["request_timeout_s"]
            ) as client:
                return await context.fetch_context(
                    client,
                    cfg["api_base"],
                    missing,
                    out_dir,
                    cfg["concurrency"],
                    known=range(scan_first, scan_last + 1),
                )

        return asyncio.run(run())

    return go


def _build(args) -> None:
    from atlas import paths
    from atlas.sources import snapshot
    from atlas.sources.acquire import raw_dir

    cfg = _load_cfg(args)
    fn = None
    if not args.no_context_fetch:
        b = json.loads((raw_dir(paths.ROOT, cfg) / "boundaries.json").read_text())
        fn = _fetch_fn(cfg, b["scan_first_id"], b["scan_last_id"])
    manifest = snapshot.build(cfg, paths.ROOT, fetch_context_fn=fn)
    print(json.dumps(manifest["counts"], indent=1))


def _verify(args) -> None:
    from atlas import paths
    from atlas.sources import snapshot

    if args.path is not None:
        sdir = Path(args.path)
    elif args.snapshot is not None:
        sdir = paths.snapshot_dir(args.snapshot)
    else:
        sdir = paths.snapshot_dir(_load_cfg(args)["snapshot_id"])
    report = snapshot.verify(sdir)
    print(json.dumps(report, indent=1))
    if not report["ok"]:
        sys.exit(1)


def register(sub) -> None:
    p = sub.add_parser("snapshot", help="Build or verify the canonical snapshot")
    sp = p.add_subparsers(dest="snapshot_cmd", required=True)
    b = sp.add_parser("build", help="Build comments/stories/context/coverage")
    b.add_argument("--config", default="configs/acquisition.toml")
    b.add_argument(
        "--no-context-fetch",
        action="store_true",
        help="Skip fetching ancestors missing from the scan range",
    )
    b.set_defaults(func=_build)
    v = sp.add_parser("verify", help="Check table hashes and schemas")
    v.add_argument("--path", default=None, help="Snapshot dir (overrides --snapshot)")
    v.add_argument("--snapshot", default=None, help="Snapshot id")
    v.add_argument("--config", default="configs/acquisition.toml")
    v.set_defaults(func=_verify)

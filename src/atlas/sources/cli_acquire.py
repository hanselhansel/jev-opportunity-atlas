"""`atlas acquire` and `atlas coverage`: the raw HN walk and its shard-level coverage."""

from __future__ import annotations

import asyncio
import json


def _run_worker(job) -> dict:
    from atlas.sources.acquire import run

    cfg, root, limit, worker = job
    return asyncio.run(run(cfg, root, limit, worker))


def _acquire(args) -> None:
    from concurrent.futures import ProcessPoolExecutor

    from atlas import paths
    from atlas.sources.acquire import load_config, locate, raw_dir, run

    cfg = load_config(paths.ROOT / args.config)
    asyncio.run(locate(cfg, raw_dir(paths.ROOT, cfg)))  # freeze once, before workers
    if args.workers == 1:
        print(
            json.dumps(asyncio.run(run(cfg, paths.ROOT, args.limit_shards)), indent=1)
        )
        return
    jobs = [
        (cfg, paths.ROOT, args.limit_shards, (i, args.workers))
        for i in range(args.workers)
    ]
    with ProcessPoolExecutor(args.workers) as pool:
        for summary in pool.map(_run_worker, jobs):
            print(json.dumps(summary), flush=True)


def _coverage(args) -> None:
    from atlas import paths
    from atlas.sources.acquire import load_config
    from atlas.sources.coverage import report

    cfg = load_config(paths.ROOT / args.config)
    print(json.dumps(report(cfg, paths.ROOT), indent=1))


def register(sub) -> None:
    a = sub.add_parser(
        "acquire", help="Fetch the HN ID range for the frozen window (resumable)"
    )
    a.add_argument("--config", default="configs/acquisition.toml")
    a.add_argument(
        "--limit-shards", type=int, default=None, help="Probe: only the first N shards"
    )
    a.add_argument(
        "--workers", type=int, default=1, help="Parallel processes (~190 ids/s each)"
    )
    a.set_defaults(func=_acquire)
    c = sub.add_parser("coverage", help="Summarize shard states and window coverage")
    c.add_argument("--config", default="configs/acquisition.toml")
    c.set_defaults(func=_coverage)

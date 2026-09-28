"""Command-line entry point: `uv run atlas <command>`."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_worker(job) -> dict:
    from atlas.sources.acquire import run

    cfg, root, limit, worker = job
    return asyncio.run(run(cfg, root, limit, worker))


def main() -> None:
    p = argparse.ArgumentParser(prog="atlas")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser(
        "acquire", help="Fetch the HN ID range for the frozen window (resumable)"
    )
    a.add_argument("--config", default="configs/acquisition.toml")
    a.add_argument(
        "--limit-shards", type=int, default=None, help="Probe: only the first N shards"
    )
    c = sub.add_parser("coverage", help="Summarize shard states and window coverage")
    c.add_argument("--config", default="configs/acquisition.toml")
    args = p.parse_args()

    from atlas.sources.acquire import load_config, run

    cfg = load_config(ROOT / args.config)
    if args.cmd == "acquire":
        from atlas.sources.acquire import locate, snapshot_dir

        asyncio.run(locate(cfg, snapshot_dir(ROOT, cfg)))  # freeze once, before workers
        if args.workers == 1:
            print(json.dumps(asyncio.run(run(cfg, ROOT, args.limit_shards)), indent=1))
        else:
            from concurrent.futures import ProcessPoolExecutor

            jobs = [(cfg, ROOT, args.limit_shards, (i, args.workers)) for i in range(args.workers)]
            with ProcessPoolExecutor(args.workers) as pool:
                for summary in pool.map(_run_worker, jobs):
                    print(json.dumps(summary), flush=True)
    elif args.cmd == "coverage":
        from atlas.sources.coverage import report

        print(json.dumps(report(cfg, ROOT), indent=1))


if __name__ == "__main__":
    main()

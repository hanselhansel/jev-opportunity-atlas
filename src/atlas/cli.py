"""Command-line entry point: `uv run atlas <command>`."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
        print(json.dumps(asyncio.run(run(cfg, ROOT, args.limit_shards)), indent=1))
    elif args.cmd == "coverage":
        from atlas.sources.coverage import report

        print(json.dumps(report(cfg, ROOT), indent=1))


if __name__ == "__main__":
    main()

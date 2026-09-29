"""`atlas screen` commands: run, table."""

from __future__ import annotations

import json


def _run(args) -> None:
    from atlas.screen.run import screen_sample

    result = screen_sample(
        args.sample,
        args.run,
        k=args.k,
        budget=args.budget,
        rpm=args.rpm,
        chunk=args.chunk,
        yes=args.yes,
    )
    if result["dispatched"]:
        print(
            json.dumps(
                {**result["run"], "stopped": result["stopped"]}, sort_keys=True
            )
        )


def _table(args) -> None:
    from atlas import paths
    from atlas.screen.unpack import build_screen_table

    table = build_screen_table(args.run)
    print(
        json.dumps(
            {
                "path": str(
                    paths.run_dir(args.run) / "screen_by_comment.parquet"
                ),
                "rows": table.num_rows,
            },
            sort_keys=True,
        )
    )


def register(sub) -> None:
    p = sub.add_parser(
        "screen", help="Main packed screen over a sample (k comments per call)"
    )
    cmds = p.add_subparsers(dest="screen_cmd", required=True)

    r = cmds.add_parser("run", help="Screen a sample, packed k comments per call")
    r.add_argument("--sample", required=True, help="Sample id")
    r.add_argument("--run", required=True, help="Run id")
    r.add_argument("--k", type=int, default=5)
    r.add_argument("--rpm", type=float, default=1000)
    r.add_argument("--chunk", type=int, default=5000)
    r.add_argument("--budget", default="screen")
    r.add_argument("--yes", action="store_true", help="Actually dispatch")
    r.set_defaults(func=_run)

    t = cmds.add_parser("table", help="Build the per-comment screen table")
    t.add_argument("--run", required=True, help="Run id")
    t.set_defaults(func=_table)

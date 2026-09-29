"""`atlas benchmark` commands: run the synthetic benchmark, write its report."""

from __future__ import annotations

import argparse
import json


def _run(args: argparse.Namespace) -> None:
    from atlas.benchmark.run import run_benchmark

    out = run_benchmark(
        args.run, budget=args.budget, yes=args.yes, version=args.cases
    )
    print(
        json.dumps(
            {
                "dispatched": out["dispatched"],
                "total_usd": out["total_usd"],
                "runs": out.get("runs"),
            },
            indent=1,
            sort_keys=True,
        )
    )


def _report(args: argparse.Namespace) -> None:
    from atlas.benchmark.score import write_report

    print(write_report(args.run))


def register(sub) -> None:
    bench = sub.add_parser(
        "benchmark", help="synthetic benchmark (invented cases)"
    )
    bsub = bench.add_subparsers(dest="benchmark_command", required=True)
    brun = bsub.add_parser(
        "run", help="estimate, then dispatch all benchmark stages with --yes"
    )
    brun.add_argument("--run", required=True)
    brun.add_argument("--budget", default="discovery")
    brun.add_argument("--yes", action="store_true")
    brun.add_argument("--cases", default="v1")
    brun.set_defaults(func=_run)
    brep = bsub.add_parser(
        "report", help="score a benchmark run and write the report"
    )
    brep.add_argument("--run", required=True)
    brep.set_defaults(func=_report)

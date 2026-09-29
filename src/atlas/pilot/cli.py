"""`atlas pilot` commands: draw, screen, facets, packed, injected, gold, report.

Paid subcommands print the stage's estimate first; without ``--yes`` nothing is
dispatched and a dry-run hint goes to stderr.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from atlas import paths


def _default_snapshot() -> str:
    cfg = tomllib.loads((paths.CONFIGS / "acquisition.toml").read_text())
    return cfg["snapshot_id"]


def _paid(out: dict) -> None:
    """After a paid stage: dry-run hint on stderr, else the run summary."""
    if not out.get("dispatched"):
        print(
            "dry run: nothing dispatched; re-run with --yes to spend",
            file=sys.stderr,
        )
        return
    print(json.dumps(out, default=str, sort_keys=True))


def _draw(args) -> None:
    from atlas.pilot.draw import pilot_draw

    snapshot = args.snapshot or _default_snapshot()
    table = pilot_draw(
        snapshot,
        n_target=args.n_target,
        min_per_stratum=args.min_per_stratum,
        seed=args.seed,
    )
    sample_id = f"pilot-{args.seed}"
    print(
        json.dumps(
            {
                "sample_id": sample_id,
                "n": table.num_rows,
                "path": str(paths.sample_path(sample_id)),
            },
            sort_keys=True,
        )
    )


def _screen(args) -> None:
    from atlas.pilot import stages

    _paid(
        stages.run_screen(
            args.sample, args.run, budget=args.budget, yes=args.yes
        )
    )


def _facets(args) -> None:
    from atlas.pilot import stages

    _paid(
        stages.run_facets(
            args.run,
            threshold=args.threshold,
            random_share=args.random_share,
            seed=args.seed,
            budget=args.budget,
            yes=args.yes,
        )
    )


def _packed(args) -> None:
    from atlas.pilot.packed import run_packed

    _paid(
        run_packed(
            args.run,
            n=args.n,
            k=args.k,
            seed=args.seed,
            budget=args.budget,
            yes=args.yes,
        )
    )


def _packed_cal(args) -> None:
    from atlas.pilot.packed_cal import run_packed_cal

    _paid(
        run_packed_cal(
            args.run, k=args.k, budget=args.budget, yes=args.yes
        )
    )


def _injected(args) -> None:
    from atlas.pilot.injected import run_injected

    _paid(run_injected(args.run, budget=args.budget, yes=args.yes))


def _gold(args) -> None:
    from atlas.pilot.gold import build_calibration

    summary = build_calibration(args.run, args.sample, seed=args.seed)
    print(json.dumps(summary, default=str, sort_keys=True))


def _report(args) -> None:
    from atlas.pilot.report import build_report

    md = build_report(args.run)
    out = (
        Path(args.out)
        if args.out
        else paths.run_dir(args.run) / "pilot_report.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)


def register(sub) -> None:
    p = sub.add_parser(
        "pilot", help="V2 pilot: draw, stages, queues, report"
    )
    cmds = p.add_subparsers(dest="pilot_cmd", required=True)

    d = cmds.add_parser(
        "draw", help="Draw the pilot sample over v2 strata (free)"
    )
    d.add_argument(
        "--snapshot", default=None,
        help="Default: snapshot_id in configs/acquisition.toml",
    )
    d.add_argument("--n-target", type=int, default=2000)
    d.add_argument("--min-per-stratum", type=int, default=20)
    d.add_argument("--seed", type=int, default=20260929)
    d.set_defaults(func=_draw)

    s = cmds.add_parser("screen", help="Screen the sample with screen@1 (paid)")
    s.add_argument("--sample", required=True)
    s.add_argument("--run", required=True)
    s.add_argument("--budget", default="pilot")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=_screen)

    f = cmds.add_parser(
        "facets", help="Facets on gate + seeded-random selection (paid)"
    )
    f.add_argument("--run", required=True)
    f.add_argument("--threshold", type=float, default=0.3)
    f.add_argument("--random-share", type=float, default=0.10)
    f.add_argument("--seed", type=int, default=1)
    f.add_argument("--budget", default="pilot")
    f.add_argument("--yes", action="store_true")
    f.set_defaults(func=_facets)

    pk = cmds.add_parser("packed", help="Packed-call experiment (paid)")
    pk.add_argument("--run", required=True)
    pk.add_argument("--n", type=int, default=500)
    pk.add_argument("--k", type=int, default=5)
    pk.add_argument("--seed", type=int, default=1)
    pk.add_argument("--budget", default="pilot")
    pk.add_argument("--yes", action="store_true")
    pk.set_defaults(func=_packed)

    pc = cmds.add_parser(
        "packed-cal",
        help="Packed screen for calibration ids missing from -packed (paid)",
    )
    pc.add_argument("--run", required=True)
    pc.add_argument("--k", type=int, default=5)
    pc.add_argument("--budget", default="pilot")
    pc.add_argument("--yes", action="store_true")
    pc.set_defaults(func=_packed_cal)

    ij = cmds.add_parser(
        "injected", help="Injected-instruction cases (paid)"
    )
    ij.add_argument("--run", required=True)
    ij.add_argument("--budget", default="pilot")
    ij.add_argument("--yes", action="store_true")
    ij.set_defaults(func=_injected)

    g = cmds.add_parser(
        "gold", help="Build calibration + audit label queues"
    )
    g.add_argument("--run", required=True)
    g.add_argument("--sample", required=True)
    g.add_argument("--seed", type=int, default=1)
    g.set_defaults(func=_gold)

    r = cmds.add_parser(
        "report", help="Markdown pilot report (local reads only)"
    )
    r.add_argument("--run", required=True)
    r.add_argument(
        "--out", default=None, help="Default: runs/<run>/pilot_report.md"
    )
    r.set_defaults(func=_report)

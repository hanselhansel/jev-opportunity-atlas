"""`atlas facets` commands: draw, estimate, run (phase-2 facet sample)."""

from __future__ import annotations

import json
import tomllib

from atlas import paths


def _default_snapshot() -> str:
    cfg = tomllib.loads((paths.CONFIGS / "acquisition.toml").read_text())
    return cfg["snapshot_id"]


def _draw(args) -> None:
    import pyarrow as pa
    import pyarrow.compute as pc

    from atlas.facets.phase2 import draw_phase2

    tbl = draw_phase2(
        args.screen_run,
        args.sample_id,
        n_pos=args.n_pos,
        n_neg=args.n_neg,
        cutoff=args.cutoff,
        seed=args.seed,
        snapshot_id=args.snapshot or _default_snapshot(),
    )
    n_pos = pc.sum(
        pc.cast(pc.equal(tbl.column("phase"), "pos"), pa.int8())
    ).as_py()
    n_neg = tbl.num_rows - n_pos
    print(f"drew {tbl.num_rows:,} ({n_pos:,} pos, {n_neg:,} neg)")


def _expand(args) -> None:
    import pyarrow as pa
    import pyarrow.compute as pc

    from atlas.facets.expand import expand_phase2

    tbl = expand_phase2(
        args.screen_run,
        args.base_sample,
        args.sample_id,
        n_pos=args.n_pos,
        seed=args.seed,
    )
    n_pos = pc.sum(
        pc.cast(pc.equal(tbl.column("phase"), "pos"), pa.int8())
    ).as_py()
    added = pc.sum(pc.cast(pc.equal(tbl.column("wave"), 2), pa.int8())).as_py()
    print(
        f"expanded {args.base_sample} -> {args.sample_id}: "
        f"{tbl.num_rows:,} rows ({n_pos:,} pos, +{added:,} added, "
        f"{tbl.num_rows - n_pos:,} neg)"
    )


def _estimate(args) -> None:
    from atlas.facets.phase2 import estimate_phase2

    print(json.dumps(estimate_phase2(args.sample_id)))


def _run(args) -> None:
    from atlas.facets.phase2 import run_phase2

    out = run_phase2(
        args.sample_id,
        args.run,
        budget=args.budget,
        rpm=args.rpm,
        chunk=args.chunk,
        yes=args.yes,
    )
    if out["dispatched"]:
        print(
            json.dumps(
                {**out["run"], "stopped": out["stopped"]}, sort_keys=True
            )
        )


def register(sub) -> None:
    p = sub.add_parser(
        "facets", help="Phase-2 facet sample and run over a screen run"
    )
    cmds = p.add_subparsers(dest="facets_cmd", required=True)

    d = cmds.add_parser(
        "draw", help="Draw the two-phase facet sample (free)"
    )
    d.add_argument("--screen-run", required=True, help="Screen run id")
    d.add_argument("--sample-id", required=True)
    d.add_argument("--n-pos", type=int, default=28_000)
    d.add_argument("--n-neg", type=int, default=2_000)
    d.add_argument("--cutoff", type=float, default=0.7)
    d.add_argument("--seed", type=int, required=True)
    d.add_argument(
        "--snapshot", default=None, help="Default: configs/acquisition.toml"
    )
    d.set_defaults(func=_draw)

    x = cmds.add_parser(
        "expand", help="Second-wave expansion of a phase-2 sample (free)"
    )
    x.add_argument("--screen-run", required=True, help="Screen run id")
    x.add_argument(
        "--base-sample", required=True, help="Existing phase-2 sample id"
    )
    x.add_argument("--sample-id", required=True, help="New sample id")
    x.add_argument(
        "--n-pos",
        type=int,
        required=True,
        help="New positive target (total, not the number to add)",
    )
    x.add_argument("--seed", type=int, required=True)
    x.set_defaults(func=_expand)

    e = cmds.add_parser(
        "estimate", help="Probe-based cost estimate for a facet sample"
    )
    e.add_argument("--sample-id", required=True)
    e.set_defaults(func=_estimate)

    r = cmds.add_parser(
        "run", help="Run facets@2 over the phase-2 sample (paid)"
    )
    r.add_argument("--sample-id", required=True)
    r.add_argument("--run", required=True, help="Run id")
    r.add_argument("--budget", default="facets")
    r.add_argument("--rpm", type=float, default=1000)
    r.add_argument("--chunk", type=int, default=5000)
    r.add_argument("--yes", action="store_true", help="Actually dispatch")
    r.set_defaults(func=_run)

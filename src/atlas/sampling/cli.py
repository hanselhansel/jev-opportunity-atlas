"""`atlas sample` commands: draw, expand, show."""

from __future__ import annotations

import json
import re
import shutil
import tomllib


def _default_snapshot() -> str:
    from atlas import paths

    cfg = tomllib.loads((paths.CONFIGS / "acquisition.toml").read_text())
    return cfg["snapshot_id"]


def _copy_sidecar(sample_id: str) -> None:
    from atlas import paths

    dest = paths.MANIFESTS / "samples"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(paths.SAMPLES / f"{sample_id}.json", dest / f"{sample_id}.json")


def _draw(args) -> None:
    from atlas import paths
    from atlas.sampling.select import draw_from_snapshot

    snapshot = args.snapshot or _default_snapshot()
    table = draw_from_snapshot(
        snapshot, args.n, args.seed, args.sample_id, args.min_per_stratum
    )
    sidecar = json.loads((paths.SAMPLES / f"{args.sample_id}.json").read_text())
    print(
        json.dumps(
            {
                "sample_id": args.sample_id,
                "n": table.num_rows,
                "path": str(paths.sample_path(args.sample_id)),
                "sha256": sidecar["sha256"],
            },
            sort_keys=True,
        )
    )


def _expand(args) -> None:
    import pyarrow.parquet as pq

    from atlas import paths
    from atlas.sampling.frame import build_frame
    from atlas.sampling.select import collapse, expand, write_manifest

    prev_path = paths.sample_path(args.sample_id)
    if not prev_path.exists():
        raise SystemExit(f"no such sample: {args.sample_id}")
    previous = pq.read_table(prev_path)
    prev_meta = json.loads((paths.SAMPLES / f"{args.sample_id}.json").read_text())
    batch = int(max(previous.column("batch").to_pylist())) + 1
    base = re.sub(r"-b\d+$", "", args.sample_id)
    new_id = f"{base}-b{batch}"
    if paths.sample_path(new_id).exists():
        raise SystemExit(f"{new_id} already exists; refusing to overwrite")

    sdir = paths.snapshot_dir(prev_meta["frame_snapshot_id"])
    comments = pq.read_table(
        sdir / "comments.parquet",
        columns=["id", "story_id", "period", "thread_type", "eligible"],
    )
    stories = pq.read_table(sdir / "stories.parquet", columns=["id", "descendants"])
    frame = build_frame(comments, stories, tuple(prev_meta["cutpoints"]))
    frame = collapse(frame, int(prev_meta["collapse_level"]))
    table = expand(
        frame, previous, args.extra, args.seed, args.min_per_stratum, sample_id=new_id
    )
    meta = {
        **prev_meta,
        "seeds_by_batch": {
            **prev_meta["seeds_by_batch"],
            str(batch): args.seed,
        },
        "parent_sample_id": args.sample_id,
    }
    write_manifest(table, meta, paths.SAMPLES)
    _copy_sidecar(new_id)
    print(
        json.dumps(
            {
                "sample_id": new_id,
                "n": table.num_rows,
                "path": str(paths.sample_path(new_id)),
            },
            sort_keys=True,
        )
    )


def _show(args) -> None:
    from atlas import paths

    sidecar = paths.SAMPLES / f"{args.sample_id}.json"
    if not sidecar.exists():
        raise SystemExit(f"no such sample: {args.sample_id}")
    meta = json.loads(sidecar.read_text())
    total_n = total_h = 0
    for label in sorted(meta["strata"]):
        s = meta["strata"][label]
        print(f"{label}\t{s['N_h']}\t{s['n_h']}")
        total_n += s["N_h"]
        total_h += s["n_h"]
    print(f"total\t{total_n}\t{total_h}")


def register(sub) -> None:
    p = sub.add_parser("sample", help="Probability samples over eligible comments")
    cmds = p.add_subparsers(dest="sample_cmd", required=True)

    d = cmds.add_parser("draw", help="Draw a stratified SRSWOR sample (idempotent)")
    d.add_argument("--snapshot", default=None, help="Default: configs/acquisition.toml")
    d.add_argument("--n", type=int, required=True)
    d.add_argument("--seed", type=int, required=True)
    d.add_argument("--sample-id", required=True)
    d.add_argument("--min-per-stratum", type=int, default=2)
    d.set_defaults(func=_draw)

    e = cmds.add_parser("expand", help="Add a recorded expansion batch")
    e.add_argument("--sample-id", required=True)
    e.add_argument("--extra", type=int, required=True)
    e.add_argument("--seed", type=int, required=True)
    e.add_argument("--min-per-stratum", type=int, default=0)
    e.set_defaults(func=_expand)

    s = cmds.add_parser("show", help="Print per-stratum N_h and n_h")
    s.add_argument("--sample-id", required=True)
    s.set_defaults(func=_show)

    _register_v2(cmds)
    _register_pooled(cmds)


def _v2_design_inputs(args) -> dict:
    """Frame, config, pilot inputs, and the yield allocation for v2 commands."""
    import numpy as np
    import pyarrow.parquet as pq

    from atlas import paths
    from atlas.sampling import design_v2, yield_alloc

    snapshot = args.snapshot or _default_snapshot()
    sdir = paths.snapshot_dir(snapshot)
    comments = pq.read_table(
        sdir / "comments.parquet",
        columns=[
            "id",
            "story_id",
            "period",
            "thread_type",
            "text_norm",
            "word_count",
            "eligible",
        ],
    )
    stories = pq.read_table(
        sdir / "stories.parquet", columns=["id", "thread_type"]
    )
    frame = design_v2.build_frame_v2(comments, stories)
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(labels, return_counts=True)
    sizes = {str(u): int(n) for u, n in zip(uniq, counts)}
    cfg = tomllib.loads((paths.CONFIGS / "sampling_v2.toml").read_text())
    p, c, levels = yield_alloc.pilot_inputs(frame, args.pilot_run, cfg)
    c = yield_alloc.scale_costs(c, args.cost_scale)
    cost_scale_source = (
        f"pilot:{args.pilot_run}-packed tokens/comment ÷ single"
        if args.cost_scale != 1.0
        else None
    )
    usd_per_token, price_version = yield_alloc.price_per_token()
    budget_tokens = yield_alloc.usd_to_tokens(args.budget_usd)
    alloc = yield_alloc.allocate_by_yield(
        sizes, p, c, budget_tokens, cfg["floor_rate"], cfg["min_n"]
    )
    return {
        "snapshot": snapshot,
        "frame": frame,
        "sizes": sizes,
        "cfg": cfg,
        "p": p,
        "c": c,
        "levels": levels,
        "usd_per_token": usd_per_token,
        "price_version": price_version,
        "budget_tokens": budget_tokens,
        "alloc": alloc,
        "cost_scale": args.cost_scale,
        "cost_scale_source": cost_scale_source,
    }


def _allocate_v2(args) -> None:
    from atlas.sampling import yield_alloc

    d = _v2_design_inputs(args)
    exp_tokens = yield_alloc.expected_tokens(d["alloc"], d["c"])
    print(
        json.dumps(
            {
                "snapshot": d["snapshot"],
                "pilot_run": args.pilot_run,
                "budget_usd": args.budget_usd,
                "budget_tokens": d["budget_tokens"],
                "price_version": d["price_version"],
                "floor_rate": d["cfg"]["floor_rate"],
                "min_n": d["cfg"]["min_n"],
                "allocation": d["alloc"],
                "N_h": d["sizes"],
                "p_h": d["p"],
                "c_h": d["c"],
                "input_levels": d["levels"],
                "expected_positives": yield_alloc.expected_positives(
                    d["alloc"], d["p"]
                ),
                "expected_tokens": exp_tokens,
                "expected_usd": exp_tokens * d["usd_per_token"],
                "largest_weight": yield_alloc.largest_weight(
                    d["alloc"], d["sizes"]
                ),
                "cost_scale": d["cost_scale"],
                "cost_scale_source": d["cost_scale_source"],
            },
            sort_keys=True,
        )
    )


def _design_v2(args) -> None:
    from atlas import paths
    from atlas.sampling import design_v2

    if paths.sample_path(args.sample_id).exists():
        raise SystemExit(
            f"{args.sample_id} already exists; refusing to overwrite"
        )
    d = _v2_design_inputs(args)
    seed = d["cfg"]["seed"]
    table = design_v2.draw_allocated(d["frame"], d["alloc"], seed, args.sample_id)
    meta = {
        "seed": seed,
        "seeds_by_batch": {"1": seed},
        "frame_snapshot_id": d["snapshot"],
        "design_version": "v2",
        "pilot_run": args.pilot_run,
        "budget_usd": args.budget_usd,
        "cost_scale": d["cost_scale"],
        "cost_scale_source": d["cost_scale_source"],
    }
    design = design_v2.design_block(
        floor_rate=d["cfg"]["floor_rate"],
        min_n=d["cfg"]["min_n"],
        budget_tokens=d["budget_tokens"],
        p=d["p"],
        c=d["c"],
        source=f"pilot:{args.pilot_run}",
        alloc=d["alloc"],
        N=d["sizes"],
        input_levels=d["levels"],
    )
    manifest = design_v2.write_design_manifest(table, meta, design, paths.SAMPLES)
    _copy_sidecar(args.sample_id)
    print(
        json.dumps(
            {
                "sample_id": args.sample_id,
                "n": table.num_rows,
                "path": str(paths.sample_path(args.sample_id)),
                "sha256": manifest["sha256"],
            },
            sort_keys=True,
        )
    )


def _register_v2(cmds) -> None:
    a = cmds.add_parser(
        "allocate-v2", help="Yield-aware allocation from pilot inputs (no draw)"
    )
    a.add_argument(
        "--snapshot", default=None, help="Default: configs/acquisition.toml"
    )
    a.add_argument("--pilot-run", required=True, help="Pilot run id")
    a.add_argument("--budget-usd", type=float, required=True)
    a.add_argument(
        "--cost-scale",
        type=float,
        default=1.0,
        help="multiply every pilot c_h before allocating, "
        "e.g. packed/single tokens per comment",
    )
    a.set_defaults(func=_allocate_v2)

    d = cmds.add_parser(
        "design-v2", help="Draw the v2 sample; never overwrites"
    )
    d.add_argument(
        "--snapshot", default=None, help="Default: configs/acquisition.toml"
    )
    d.add_argument("--pilot-run", required=True, help="Pilot run id")
    d.add_argument("--budget-usd", type=float, required=True)
    d.add_argument("--sample-id", required=True)
    d.add_argument(
        "--cost-scale",
        type=float,
        default=1.0,
        help="multiply every pilot c_h before allocating, "
        "e.g. packed/single tokens per comment",
    )
    d.set_defaults(func=_design_v2)


def _draw_pooled(args) -> None:
    import tomllib

    from atlas import paths
    from atlas.sampling import pooled

    cfg = tomllib.loads((paths.CONFIGS / "sampling_v2.toml").read_text())
    out = pooled.draw_pooled(
        snapshot_id=args.snapshot or _default_snapshot(),
        pilot_run=args.pilot_run,
        budget_usd=args.budget_usd,
        cost_scale=args.cost_scale,
        cutoff=args.cutoff,
        seed=args.seed,
        sample_id=args.sample_id,
        floor_rate=cfg["floor_rate"],
        min_n=cfg["min_n"],
        min_pilot_n=cfg["min_pilot_n"],
    )
    alloc = out["alloc"]
    n = sum(alloc.values())
    h1 = sum(v for k, v in alloc.items() if "|H1|" in k)
    print(
        f"n={n:,}  H1={h1:,}  H2={n - h1:,}  "
        f"expected positives (>= {args.cutoff}) = "
        f"{out['expected_positives']:,.0f}"
    )
    print(
        f"expected tokens {out['expected_tokens']:,.0f} of "
        f"{out['budget_tokens']:,}; largest weight {out['largest_weight']:.1f}"
    )
    if not out["reused"]:
        _copy_sidecar(args.sample_id)
    print(
        json.dumps(
            {
                "written": str(paths.sample_path(args.sample_id)),
                "rows": out["rows"],
                "reused": out["reused"],
            }
        )
    )


def _register_pooled(cmds) -> None:
    d = cmds.add_parser(
        "draw-pooled",
        help="Main breadth draw: pilot inputs pooled across half-years",
    )
    d.add_argument(
        "--snapshot", default=None, help="Default: configs/acquisition.toml"
    )
    d.add_argument("--pilot-run", required=True, help="Pilot run id")
    d.add_argument("--budget-usd", type=float, required=True)
    d.add_argument(
        "--cost-scale",
        type=float,
        required=True,
        help="multiply every pilot c_h before allocating, "
        "e.g. packed/single tokens per comment (main run used 0.424)",
    )
    d.add_argument(
        "--cutoff",
        type=float,
        default=0.7,
        help="firsthand_problem noul counts as positive at or above this",
    )
    d.add_argument("--seed", type=int, required=True)
    d.add_argument("--sample-id", required=True)
    d.set_defaults(func=_draw_pooled)

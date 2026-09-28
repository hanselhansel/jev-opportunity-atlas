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

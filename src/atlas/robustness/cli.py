"""`atlas robust` commands: paraphrase-robustness subsamples, reruns, compares."""

from __future__ import annotations

import json


def _subsample_screen(args) -> None:
    from atlas import paths
    from atlas.robustness.subsample import subsample_screen

    table = subsample_screen(args.sample, args.n, args.seed, args.sample_id)
    print(
        json.dumps(
            {
                "sample_id": args.sample_id,
                "n": table.num_rows,
                "path": str(paths.sample_path(args.sample_id)),
            },
            sort_keys=True,
        )
    )


def _subsample_items(args) -> None:
    from atlas.robustness.subsample import subsample_items

    table = subsample_items(args.items, args.n, args.seed, args.out)
    print(
        json.dumps(
            {"n": table.num_rows, "path": str(args.out)}, sort_keys=True
        )
    )


def register(sub) -> None:
    p = sub.add_parser(
        "robust", help="Paraphrase-robustness subsamples, reruns, compares"
    )
    cmds = p.add_subparsers(dest="robust_cmd", required=True)

    s = cmds.add_parser(
        "subsample-screen",
        help="Stratified SRSWOR subsample of a screen sample",
    )
    s.add_argument("--sample", required=True, help="Parent sample id")
    s.add_argument("--n", type=int, required=True)
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--sample-id", required=True, help="New sample id")
    s.set_defaults(func=_subsample_screen)

    i = cmds.add_parser(
        "subsample-items",
        help="Seeded SRSWOR of an items parquet, sorted by comment_id",
    )
    i.add_argument("--items", required=True, help="Input parquet path")
    i.add_argument("--n", type=int, required=True)
    i.add_argument("--seed", type=int, required=True)
    i.add_argument("--out", required=True, help="Output parquet path")
    i.set_defaults(func=_subsample_items)

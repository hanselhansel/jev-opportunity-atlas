"""`atlas robust` commands: paraphrase-robustness subsamples, reruns, compares."""

from __future__ import annotations

import asyncio
import json


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def _load_paraphrases() -> dict:
    from atlas import paths

    path = paths.CONFIGS / "cards" / "paraphrases.v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["paraphrases"]


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

    a = cmds.add_parser(
        "assign-paraphrase",
        help="Run assign with a paraphrased instruction pair",
    )
    a.add_argument("--cardset", required=True)
    a.add_argument("--version", required=True)
    a.add_argument("--items", required=True, help="Subsampled items parquet")
    a.add_argument("--run", required=True)
    a.add_argument("--para", type=int, choices=[1, 2], required=True)
    a.add_argument("--rpm", type=float, default=1000)
    a.add_argument("--budget", default="robustness")
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=_assign_paraphrase)

    cs = cmds.add_parser(
        "compare-screen",
        help="Compare paraphrase screen runs against the main run",
    )
    cs.add_argument("--main-run", required=True)
    cs.add_argument(
        "--runs", required=True, help="Comma-separated paraphrase run ids"
    )
    cs.add_argument("--sample", required=True, help="Robustness subsample id")
    cs.add_argument("--cutoff", type=float, default=0.7)
    cs.add_argument("--n-boot", type=int, default=2000)
    cs.add_argument("--seed", type=int, default=0)
    cs.add_argument("--out", required=True, help="Output JSON path")
    cs.set_defaults(func=_compare_screen)

    ca = cmds.add_parser(
        "compare-assign",
        help="Compare paraphrase assignment runs against the main run",
    )
    ca.add_argument("--main-run", required=True)
    ca.add_argument(
        "--runs", required=True, help="Comma-separated paraphrase run ids"
    )
    ca.add_argument("--version", required=True, help="Taxonomy version")
    ca.add_argument("--out", required=True, help="Output JSON path")
    ca.set_defaults(func=_compare_assign)


def _write_out(path, obj) -> None:
    import os
    from pathlib import Path

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, out)


def _compare_screen(args) -> None:
    from atlas.robustness.compare import compare_screen

    runs = [r.strip() for r in args.runs.split(",") if r.strip()]
    out = compare_screen(
        args.main_run,
        runs,
        args.sample,
        cutoff=args.cutoff,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    _write_out(args.out, out)
    print(json.dumps({"path": str(args.out), "runs": runs}, sort_keys=True))


def _compare_assign(args) -> None:
    from atlas.robustness.compare import compare_assign

    runs = [r.strip() for r in args.runs.split(",") if r.strip()]
    out = compare_assign(args.main_run, runs, args.version)
    _write_out(args.out, out)
    print(json.dumps({"path": str(args.out), "runs": runs}, sort_keys=True))


def _assign_paraphrase(args) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from atlas import paths
    from atlas.cards.engine import cli as cards_cli
    from atlas.cards.engine.assign import (
        assign,
        card_item,
        group_item,
        write_assignments,
    )
    from atlas.cards.engine.cardset import load_cardset
    from atlas.inference import keys
    from atlas.inference.budget import BudgetGuard
    from atlas.inference.client import JevClient
    from atlas.inference.runner import RunContext

    pair = _load_paraphrases()[str(args.para)]
    budgets, price_row, usd_per_token = cards_cli._load_configs()
    cap, worst = cards_cli._budget_cap(budgets, args.budget)
    cs = load_cardset(args.cardset, args.version)
    rows = pq.read_table(args.items).to_pylist()
    biggest = max(cs.groups, key=lambda g: len(cs.cards_in(g)))
    tokens = []
    for r in rows:
        tokens.append(
            cards_cli._est_tokens(
                group_item(
                    r["comment_id"], r["pain_sentence"], r["sentences"], cs,
                    instructions=pair["group_instructions"],
                )
            )
        )
        tokens.append(
            cards_cli._est_tokens(
                card_item(
                    r["comment_id"], r["pain_sentence"], r["sentences"], cs,
                    biggest, instructions=pair["card_instructions"],
                )
            )
        )
    cards_cli._print_estimate(
        f"assign-para{args.para}", tokens, args.budget, cap, usd_per_token
    )
    if not args.yes:
        return
    guard = BudgetGuard.for_budget(args.budget, cap, usd_per_token, worst)
    try:
        client = JevClient(
            api_key=keys.get_api_key(),
            base=keys.base_url(),
            transport=_transport(),
        )
        ctx = RunContext(
            run_id=args.run,
            client=client,
            guard=guard,
            model=cards_cli.MODEL,
            price_version=price_row["version"],
            run_dir=paths.run_dir(args.run),
            budget=args.budget,
            rpm=args.rpm,
        )
        result = asyncio.run(
            assign(
                ctx,
                rows,
                cs,
                question_set_prefix=f"assign-para{args.para}",
                group_instructions=pair["group_instructions"],
                card_instructions=pair["card_instructions"],
            )
        )
        run_dir = paths.run_dir(args.run)
        pain = [
            {"comment_id": r["comment_id"], "pain_sentence": r["pain_sentence"]}
            for r in rows
        ]
        pq.write_table(
            pa.Table.from_pylist(pain, schema=cards_cli.PAIN_SCHEMA),
            str(run_dir / "pain.parquet"),
        )
        write_assignments(run_dir, result, cs.version)
    finally:
        guard.close()

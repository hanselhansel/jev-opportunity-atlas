"""Extra `cards` subcommands registered from `cli`: planted, replies,
residue, induce, combine.

Handlers call back into `cli` for the shared helpers so the test
monkeypatch points (`cli._transport`, `cli.RunContext`) keep working.
"""

from __future__ import annotations

import json
import shutil

import pyarrow.parquet as pq

from atlas import paths
from atlas.cards import replies_run
from atlas.cards.engine import cli
from atlas.cards.engine.assign import (
    assign,
    load_assignments,
    residue_sample,
    write_assignments,
)
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.combine import combine
from atlas.cards.engine.induce import (
    check_superset,
    induce,
    induce_stats,
    scope_items,
    write_induce_sidecar,
)
from atlas.cards.engine.planted import (
    load_planted,
    planted_items,
    planted_score,
    with_planted,
)


def register(commands, common) -> None:
    pp = commands.add_parser("planted", help="run the planted-needs check")
    common(pp, "merge_verify")
    pp.add_argument("--planted", default="v1")
    pp.set_defaults(func=_cmd_planted)

    xp = commands.add_parser(
        "replies", help="unsolved-replies check over an assign run"
    )
    xp.add_argument("--run", required=True, help="assign run id")
    xp.add_argument("--version", required=True)
    xp.add_argument("--snapshot", required=True)
    xp.add_argument("--budget", default="replies")
    xp.add_argument("--top-cards", type=int, default=None)
    xp.add_argument("--max-replies", type=int, default=5)
    xp.add_argument("--rpm", type=float, default=1000)
    xp.add_argument("--concurrency", type=int, default=8)
    xp.add_argument("--yes", action="store_true")
    xp.set_defaults(func=_cmd_replies)

    rp = commands.add_parser("residue", help="sample unassigned comments")
    rp.add_argument("--run", required=True)
    rp.add_argument("--version", required=True)
    rp.add_argument("--k", type=int, default=200)
    rp.add_argument("--seed", type=int, default=1)
    rp.set_defaults(func=_cmd_residue)

    ip = commands.add_parser(
        "induce", help="reassign card-level residue under a superset cardset"
    )
    common(ip, "assign")
    ip.add_argument("--base-run", required=True)
    ip.add_argument("--base-version", required=True)
    ip.add_argument(
        "--items",
        required=True,
        help="parquet: comment_id, pain_sentence, sentences",
    )
    ip.add_argument(
        "--scope",
        choices=["residue", "all"],
        default="residue",
        help="card-level re-ask set: residue only (default) or every row "
        "with a real group",
    )
    ip.set_defaults(func=_cmd_induce)

    cp = commands.add_parser(
        "combine", help="merge assign runs of one version into a new run"
    )
    cp.add_argument(
        "--runs", required=True, help="comma-separated assign run ids"
    )
    cp.add_argument("--version", required=True)
    cp.add_argument("--run", required=True, help="output run id")
    cp.set_defaults(func=_cmd_combine)


def _cmd_planted(args) -> None:
    budgets, price_row, usd_per_token = cli._load_configs()
    cap, worst = cli._budget_cap(budgets, args.budget)
    planted = load_planted(args.planted)
    cs = with_planted(load_cardset(args.cardset, args.version), planted)
    items = planted_items(planted)
    cli._print_estimate(
        "planted", cli._assign_tokens(items, cs), args.budget, cap, usd_per_token
    )
    if not args.yes:
        return
    ctx = cli._run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        result = cli._run_or_exit(assign(ctx, items, cs))
    finally:
        ctx.guard.close()
    print(json.dumps(planted_score(result.rows, planted), indent=1))


def _cmd_combine(args) -> None:
    run_ids = [r.strip() for r in args.runs.split(",") if r.strip()]
    print(json.dumps(combine(run_ids, args.version, args.run), indent=1))


def _cmd_residue(args) -> None:
    result = load_assignments(paths.run_dir(args.run), args.version)
    print(json.dumps(residue_sample(result.rows, args.k, args.seed), indent=1))


def _cmd_induce(args) -> None:
    budgets, price_row, usd_per_token = cli._load_configs()
    cap, worst = cli._budget_cap(budgets, args.budget)
    base_cs = load_cardset(args.cardset, args.base_version)
    new_cs = load_cardset(args.cardset, args.version)
    if args.base_version == args.version:
        if args.scope != "all":
            raise SystemExit(
                "--base-version equals --version only with --scope all"
            )
    else:
        check_superset(base_cs, new_cs)
    base_run_dir = paths.run_dir(args.base_run)
    base_result = load_assignments(base_run_dir, args.base_version)
    off_version = [
        r["comment_id"]
        for r in base_result.rows
        if r["taxonomy_version"] != args.base_version
    ]
    if off_version:
        raise ValueError(
            f"base run {args.base_run} carries {len(off_version)} rows whose "
            f"taxonomy_version is not {args.base_version!r} "
            f"(first: {off_version[:5]})"
        )
    items_by_cid = {
        r["comment_id"]: r for r in pq.read_table(args.items).to_pylist()
    }
    level2 = scope_items(
        base_result.rows, items_by_cid, new_cs, args.scope
    )
    cli._print_estimate(
        "induce",
        {"assign_card": [cli._est_tokens(it) for it in level2]},
        args.budget,
        cap,
        usd_per_token,
    )
    if not args.yes:
        return
    ctx = cli._run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        result = cli._run_or_exit(
            induce(ctx, base_result, items_by_cid, new_cs, args.scope)
        )
        run_dir = paths.run_dir(args.run)
        run_dir.mkdir(parents=True, exist_ok=True)
        src_pain = base_run_dir / "pain.parquet"
        if not src_pain.exists():
            raise SystemExit(f"{src_pain} missing: base run is incomplete")
        shutil.copyfile(src_pain, run_dir / "pain.parquet")
        write_assignments(run_dir, result, new_cs.version)
        stats = induce_stats(
            base_cs, new_cs, base_result.rows, result.rows,
            args.run, args.base_run, scope=args.scope,
        )
        write_induce_sidecar(run_dir, stats, new_cs.version)
    finally:
        ctx.guard.close()
    print(json.dumps(stats, indent=1))


def _cmd_replies(args) -> None:
    budgets, price_row, usd_per_token = cli._load_configs()
    cap, worst = cli._budget_cap(budgets, args.budget)
    run_dir = paths.run_dir(args.run)
    result = load_assignments(run_dir, args.version)
    pain = {
        r["comment_id"]: r["pain_sentence"]
        for r in pq.read_table(run_dir / "pain.parquet").to_pylist()
    }
    problem_ids = replies_run.selected_problems(result.rows, args.top_cards)
    items = replies_run.collect_items(
        paths.snapshot_dir(args.snapshot),
        problem_ids,
        pain,
        max_replies=args.max_replies,
    )
    tokens = [replies_run.item_tokens(it) for it in items]
    cli._print_estimate(
        "replies", {"replies": tokens}, args.budget, cap, usd_per_token
    )
    if not args.yes:
        return
    ctx = cli._run_ctx(args, price_row, cap, worst, usd_per_token)
    ctx.run_dir = run_dir / "replies"
    try:
        cli._run_or_exit(replies_run.run(ctx, items))
    finally:
        ctx.guard.close()
    answers = replies_run.answers_table(ctx.run_dir)
    out = replies_run.write_outputs(ctx.run_dir, items, answers)
    print(
        json.dumps(
            {**out, "problems": len(problem_ids), "items": len(items)},
            indent=1,
        )
    )

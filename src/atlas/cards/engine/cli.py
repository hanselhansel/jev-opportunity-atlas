"""`cards` commands: assign, merge, verify, planted, residue.

Every Jev command prints a cost estimate first and requires --yes to proceed.
The API key is read only through atlas.inference.keys at call time.
"""

from __future__ import annotations

import asyncio
import json
import math
import tomllib

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.cards import items as items_mod
from atlas.cards import replies_run
from atlas.cards.engine.assign import (
    AssignResult,
    assign,
    card_item,
    group_item,
    load_assignments,
    residue_sample,
    write_assignments,
)
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.merge import (
    merge_item,
    merge_pairs,
    propose_merges,
    score_merges,
)
from atlas.cards.engine.planted import (
    load_planted,
    planted_items,
    planted_score,
    with_planted,
)
from atlas.cards.engine.verify import verifiable, verify, verify_item
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.questions import canonical_json
from atlas.inference.runner import RunContext

MODEL = "jev-1.13.0"
PAIN_SCHEMA = pa.schema(
    [("comment_id", pa.int64()), ("pain_sentence", pa.string())]
)


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def register(sub) -> None:
    parser = sub.add_parser("cards", help="need-card engine")
    commands = parser.add_subparsers(dest="cards_command", required=True)

    def common(p, budget):
        p.add_argument("--cardset", required=True)
        p.add_argument("--version", required=True)
        p.add_argument("--run", required=True)
        p.add_argument("--budget", default=budget)
        p.add_argument("--rpm", type=float, default=1000)
        p.add_argument("--concurrency", type=int, default=8)
        p.add_argument("--yes", action="store_true")

    ap = commands.add_parser("assign", help="assign comments to need cards")
    common(ap, "assign")
    ap.add_argument("--items", required=True, help="parquet: comment_id, pain_sentence, sentences")
    ap.set_defaults(func=_cmd_assign)

    mp = commands.add_parser("merge", help="score card-merge candidates")
    common(mp, "merge_verify")
    mp.add_argument(
        "--all-pairs",
        action="store_true",
        help="score every pair of active cards, not just evidenced pairs",
    )
    mp.set_defaults(func=_cmd_merge)

    vp = commands.add_parser("verify", help="verify card membership")
    common(vp, "merge_verify")
    vp.set_defaults(func=_cmd_verify)

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

    items_mod.register(commands)


def _load_configs():
    configs = paths.CONFIGS
    budgets = tomllib.loads((configs / "budgets.toml").read_text(encoding="utf-8"))
    prices = tomllib.loads((configs / "prices.toml").read_text(encoding="utf-8"))
    price_row = next(r for r in prices["price"] if r["model"] == MODEL)
    return budgets, price_row, price_row["input_usd_per_million"] / 1e6


def _budget_cap(budgets, name):
    if name not in budgets or name.startswith("worst_case"):
        raise SystemExit(
            f"unknown budget {name!r} in {paths.CONFIGS / 'budgets.toml'}"
        )
    return budgets[name], budgets["worst_case_tokens_per_unknown_attempt"]


def _est_tokens(item: dict) -> int:
    body = {"state": item["state"], "model": MODEL, "questions": item["questions"]}
    return math.ceil(len(canonical_json(body).encode("utf-8")) / 3.2)


def _assign_tokens(rows, cs) -> list[int]:
    biggest = max(cs.groups, key=lambda g: len(cs.cards_in(g)))
    tokens = []
    for r in rows:
        tokens.append(
            _est_tokens(
                group_item(r["comment_id"], r["pain_sentence"], r["sentences"], cs)
            )
        )
        tokens.append(
            _est_tokens(
                card_item(
                    r["comment_id"], r["pain_sentence"], r["sentences"], cs, biggest
                )
            )
        )
    return tokens


def _print_estimate(command, tokens, budget, cap, usd_per_token) -> None:
    total = sum(tokens)
    print(
        json.dumps(
            {
                "command": command,
                "estimated_calls": len(tokens),
                "estimated_input_tokens": total,
                "estimated_usd": total * usd_per_token,
                "budget": budget,
                "cap_usd": cap,
            },
            indent=1,
        )
    )


def _run_ctx(args, price_row, cap, worst, usd_per_token) -> RunContext:
    guard = BudgetGuard.for_budget(args.budget, cap, usd_per_token, worst)
    try:
        client = JevClient(
            api_key=keys.get_api_key(),
            base=keys.base_url(),
            transport=_transport(),
        )
        return RunContext(
            run_id=args.run,
            client=client,
            guard=guard,
            model=MODEL,
            price_version=price_row["version"],
            run_dir=paths.run_dir(args.run),
            budget=args.budget,
            rpm=args.rpm,
            concurrency=args.concurrency,
        )
    except BaseException:
        guard.close()
        raise


def _cmd_assign(args) -> None:
    budgets, price_row, usd_per_token = _load_configs()
    cap, worst = _budget_cap(budgets, args.budget)
    cs = load_cardset(args.cardset, args.version)
    rows = pq.read_table(args.items).to_pylist()
    _print_estimate("assign", _assign_tokens(rows, cs), args.budget, cap, usd_per_token)
    if not args.yes:
        return
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        result = asyncio.run(assign(ctx, rows, cs))
        run_dir = paths.run_dir(args.run)
        pain = [
            {"comment_id": r["comment_id"], "pain_sentence": r["pain_sentence"]}
            for r in rows
        ]
        pq.write_table(
            pa.Table.from_pylist(pain, schema=PAIN_SCHEMA), str(run_dir / "pain.parquet")
        )
        write_assignments(run_dir, result, cs.version)
    finally:
        ctx.guard.close()


def _cmd_merge(args) -> None:
    budgets, price_row, usd_per_token = _load_configs()
    cap, worst = _budget_cap(budgets, args.budget)
    cs = load_cardset(args.cardset, args.version)
    run_dir = paths.run_dir(args.run)
    result = load_assignments(run_dir, args.version)
    pairs = merge_pairs(cs, result, all_pairs=args.all_pairs)
    tokens = [_est_tokens(merge_item(cs.version, a, b, cs)) for a, b in pairs]
    _print_estimate("merge", tokens, args.budget, cap, usd_per_token)
    if not args.yes:
        return
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        scored = asyncio.run(score_merges(ctx, pairs, cs))
    finally:
        ctx.guard.close()
    proposals = propose_merges(scored)
    out = {"scored": scored, "proposals": proposals}
    (run_dir / f"merge-{cs.version}.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(proposals, indent=1))


def _cmd_verify(args) -> None:
    budgets, price_row, usd_per_token = _load_configs()
    cap, worst = _budget_cap(budgets, args.budget)
    cs = load_cardset(args.cardset, args.version)
    run_dir = paths.run_dir(args.run)
    result = load_assignments(run_dir, args.version)
    pain = {
        r["comment_id"]: r["pain_sentence"]
        for r in pq.read_table(run_dir / "pain.parquet").to_pylist()
    }
    tokens = [
        _est_tokens(verify_item(row, pain[row["comment_id"]], cs))
        for row in result.rows
        if verifiable(row, pain)
    ]
    _print_estimate("verify", tokens, args.budget, cap, usd_per_token)
    if not args.yes:
        return
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        rows = asyncio.run(verify(ctx, result, pain, cs))
    finally:
        ctx.guard.close()
    write_assignments(run_dir, AssignResult(rows=rows, meta=result.meta), cs.version)
    print(json.dumps({"verified": sum(1 for r in rows if r["verified_p"] is not None)}))


def _cmd_planted(args) -> None:
    budgets, price_row, usd_per_token = _load_configs()
    cap, worst = _budget_cap(budgets, args.budget)
    planted = load_planted(args.planted)
    cs = with_planted(load_cardset(args.cardset, args.version), planted)
    items = planted_items(planted)
    _print_estimate(
        "planted", _assign_tokens(items, cs), args.budget, cap, usd_per_token
    )
    if not args.yes:
        return
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        result = asyncio.run(assign(ctx, items, cs))
    finally:
        ctx.guard.close()
    print(json.dumps(planted_score(result.rows, planted), indent=1))


def _cmd_residue(args) -> None:
    result = load_assignments(paths.run_dir(args.run), args.version)
    print(json.dumps(residue_sample(result.rows, args.k, args.seed), indent=1))


def _cmd_replies(args) -> None:
    budgets, price_row, usd_per_token = _load_configs()
    cap, worst = _budget_cap(budgets, args.budget)
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
    _print_estimate("replies", tokens, args.budget, cap, usd_per_token)
    if not args.yes:
        return
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token)
    ctx.run_dir = run_dir / "replies"
    try:
        asyncio.run(replies_run.run(ctx, items))
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

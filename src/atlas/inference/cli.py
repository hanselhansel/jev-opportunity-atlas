"""jev commands: `jev smoke` (one live call through the full runner) and
`jev ledger` (ledger summary). The smoke item is fully synthetic; the API key
is loaded from env/Keychain and never printed or stored."""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from datetime import UTC, datetime

import pyarrow.parquet as pq

from atlas import paths
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.ledger import summarize
from atlas.inference.questions import load_question_set
from atlas.inference.runner import RunContext, run_batch

MODEL = "jev-1.13.0"

_SMOKE_SENTENCES = [
    "I spend two hours every week reconciling invoices by hand because our accounting tool has no bank sync.",
    "I tried two other tools.",
    "Neither handled multi-currency.",
]
SMOKE_ITEM = {
    "comment_id": 9_000_000_001,
    "comment": " ".join(_SMOKE_SENTENCES),
    "parent": "",
    "story_title": "Ask HN: What manual work do you still do every week?",
    "thread_type": "ask_hn",
    "sentences": list(_SMOKE_SENTENCES),
}


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def register(sub) -> None:
    parser = sub.add_parser("jev", help="TypeSafe Jev inference")
    commands = parser.add_subparsers(dest="jev_command", required=True)

    smoke_p = commands.add_parser("smoke", help="one synthetic call, end to end")
    smoke_p.add_argument("--budget", default="smoke")
    smoke_p.add_argument(
        "--set", dest="question_set", default="screen", choices=["screen", "deep"]
    )
    smoke_p.set_defaults(func=_cmd_smoke)

    ledger_p = commands.add_parser("ledger", help="print a run's ledger summary")
    ledger_p.add_argument("--run", required=True)
    ledger_p.add_argument("--by", default=None, choices=["question_set"])
    ledger_p.set_defaults(func=_cmd_ledger)


def _cmd_ledger(args) -> None:
    print(json.dumps(summarize(paths.ledger_path(args.run), by=args.by), indent=1))


def _smoke_checks(run_dir, qs, n_sentences: int) -> dict:
    rows = {r["question_id"]: r for r in pq.read_table(run_dir / "answers").to_pylist()}
    support = rows["support_sentence"]["choice"] or ""
    m = re.fullmatch(r"s(\d+)", support)
    return {
        "user_role_in_options": rows["user_role"]["choice"]
        in list(qs.questions["user_role"]["criteria"]),
        "specificity_numeric": isinstance(rows["specificity"]["score"], (int, float))
        and not isinstance(rows["specificity"]["score"], bool),
        "support_sentence_valid": m is not None and int(m.group(1)) < n_sentences,
    }


def _cmd_smoke(args) -> None:
    budgets = tomllib.loads((paths.CONFIGS / "budgets.toml").read_text(encoding="utf-8"))
    prices = tomllib.loads((paths.CONFIGS / "prices.toml").read_text(encoding="utf-8"))
    if args.budget not in budgets or args.budget.startswith("worst_case"):
        raise SystemExit(f"unknown budget {args.budget!r} in {paths.CONFIGS / 'budgets.toml'}")
    cap = budgets[args.budget]
    worst = budgets["worst_case_tokens_per_unknown_attempt"]
    price_row = next(r for r in prices["price"] if r["model"] == MODEL)
    usd_per_token = price_row["input_usd_per_million"] / 1e6

    qs = load_question_set(args.question_set, 0)
    run_id = "smoke-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = paths.run_dir(run_id)
    guard = BudgetGuard.for_budget(args.budget, cap, usd_per_token, worst)
    try:
        client = JevClient(
            api_key=keys.get_api_key(),
            base=keys.base_url(),
            transport=_transport(),
        )
        ctx = RunContext(
            run_id=run_id,
            client=client,
            guard=guard,
            model=MODEL,
            price_version=price_row["version"],
            run_dir=run_dir,
            cache_path=run_dir / "smoke-cache.sqlite",
            concurrency=1,
            budget=args.budget,
        )
        out = asyncio.run(run_batch(ctx, [dict(SMOKE_ITEM)], qs))
        checks = (
            _smoke_checks(run_dir, qs, len(SMOKE_ITEM["sentences"]))
            if args.question_set == "deep"
            else {}
        )
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "run": out,
                    "ledger": summarize(run_dir / "ledger.jsonl"),
                    "checks": checks,
                },
                indent=1,
            )
        )
    finally:
        guard.close()

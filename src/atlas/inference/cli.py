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
from atlas.inference.balance import reconcile, record_balance
from atlas.inference.budget import (
    BudgetGuard,
    budget_names,
    load_budgets,
    scan_runs,
)
from atlas.inference.client import JevClient
from atlas.inference.estimate import (
    estimate_cost,
    fit_calibration,
    input_price,
    load_label,
)
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

    budget_p = commands.add_parser(
        "budget", help="per-name and account headroom (read-only)"
    )
    budget_p.set_defaults(func=_cmd_budget)

    est_p = commands.add_parser(
        "estimate", help="estimated cost of an items parquet before dispatch"
    )
    est_p.add_argument("--set", dest="question_set", required=True)
    est_p.add_argument("--items", required=True)
    est_p.add_argument("--calibrate-with", dest="calibrate_with", default=None)
    est_p.set_defaults(func=_cmd_estimate)

    m = commands.add_parser(
        "measure",
        help="measured input tokens per set on 3 synthetic comments (paid)",
    )
    m.add_argument(
        "--sets", default="screen@1,facets@1",
        help="comma-separated name@version question sets",
    )
    m.add_argument("--budget", default="smoke")
    m.add_argument(
        "--yes", action="store_true", help="Actually dispatch"
    )
    m.set_defaults(func=_cmd_measure)

    bal_p = commands.add_parser("balance", help="credit balance log")
    bal_sub = bal_p.add_subparsers(dest="balance_command", required=True)
    bal_rec = bal_sub.add_parser(
        "record", help="record the balance shown in the TypeSafe console"
    )
    bal_rec.add_argument("usd", type=float)
    bal_rec.add_argument("--note", default="")
    bal_rec.set_defaults(func=_cmd_balance_record)
    bal_recon = bal_sub.add_parser(
        "reconcile", help="compare balance deltas against ledger spend"
    )
    bal_recon.set_defaults(func=_cmd_balance_reconcile)


def _cmd_ledger(args) -> None:
    print(json.dumps(summarize(paths.ledger_path(args.run), by=args.by), indent=1))


_EMPTY_SCAN = {
    "calculated_usd": 0.0,
    "unknown_attempts": 0,
    "pending_attempts": 0,
    "runs": 0,
}


def _committed_usd(entry: dict, worst: float, price: float) -> float:
    """Committed spend as the guard sees it: calculated plus every unknown
    attempt (settled or still pending) at the flat worst case."""
    return entry["calculated_usd"] + entry["unknown_attempts"] * worst * price


def _name_status(cap, entry: dict, worst: float, price: float) -> dict:
    pending = entry["pending_attempts"]
    unknown_usd = (entry["unknown_attempts"] - pending) * worst * price
    reserved_usd = pending * worst * price
    committed = _committed_usd(entry, worst, price)
    has_cap = isinstance(cap, (int, float)) and not isinstance(cap, bool)
    return {
        "cap_usd": cap if has_cap else None,
        "calculated_usd": entry["calculated_usd"],
        "unknown_attempts": entry["unknown_attempts"] - pending,
        "unknown_usd": unknown_usd,
        "reserved_usd": reserved_usd,
        "committed_usd": committed,
        "remaining_usd": cap - committed if has_cap else None,
    }


def _cmd_budget(args) -> None:
    # Read-only: takes no locks, so it works while a run holds them.
    cfg = load_budgets()
    price = input_price(MODEL)
    worst = cfg.get("worst_case_tokens_per_unknown_attempt", 0)
    scan = scan_runs()
    names = {
        name: _name_status(cfg.get(name), scan.get(name, _EMPTY_SCAN), worst, price)
        for name in sorted(set(budget_names(cfg)) | set(scan))
    }
    committed = sum(
        _committed_usd(scan.get(name, _EMPTY_SCAN), worst, price) for name in names
    )
    total = cfg.get("account_total")
    print(
        json.dumps(
            {
                "names": names,
                "account": {
                    "total_usd": total,
                    "committed_usd": committed,
                    "remaining_usd": (
                        total - committed if total is not None else None
                    ),
                },
            },
            indent=1,
        )
    )


def _cmd_estimate(args) -> None:
    qs = load_label(args.question_set)
    items = pq.read_table(args.items).to_pylist()
    cal_items = (
        pq.read_table(args.calibrate_with).to_pylist()
        if args.calibrate_with
        else items
    )
    calibration = fit_calibration(
        sorted(paths.RUNS.glob("*/ledger.jsonl")), cal_items, model=MODEL
    )
    price = input_price(MODEL)
    out = estimate_cost(items, qs, MODEL, calibration, usd_per_input_token=price)
    cfg = load_budgets()
    worst = cfg.get("worst_case_tokens_per_unknown_attempt", 0)
    remaining = None
    if cfg.get("account_total") is not None:
        committed = sum(
            _committed_usd(s, worst, price) for s in scan_runs().values()
        )
        remaining = cfg["account_total"] - committed
    out["account_remaining_usd"] = remaining
    out["share_of_remaining"] = (
        out["est_usd"] / remaining if remaining and remaining > 0 else None
    )
    print(json.dumps(out, indent=1))


def _cmd_measure(args) -> None:
    from atlas.inference.measure import measure_tokens

    measure_tokens(args.sets, budget=args.budget, yes=args.yes)


def _cmd_balance_record(args) -> None:
    print(json.dumps(record_balance(args.usd, note=args.note), indent=1))


def _cmd_balance_reconcile(args) -> None:
    print(json.dumps(reconcile(), indent=1))


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
    if args.budget not in budget_names(budgets):
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

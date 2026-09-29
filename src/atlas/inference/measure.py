"""`jev measure`: real input-token counts per question set (L22).

Runs three fully synthetic comments (short/medium/long) through the project
runner for each requested set, so every call lands in the ledger under
budget ``smoke`` and the printed table shows measured tokens, not the
bytes/3.2 estimate. Ported from the main run's measure_tokens script
(docs/measurements/2026-09-28-token-costs.md); see docs/runbook-main-run.md.
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from datetime import UTC, datetime

from atlas import paths
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard, budget_names
from atlas.inference.client import JevClient
from atlas.inference.estimate import estimate_cost, input_price
from atlas.inference.ledger import read_rows, summarize
from atlas.inference.questions import load_question_set
from atlas.inference.runner import RunContext, run_batch

MODEL = "jev-1.13.0"
FIRST_ID = 9_900_000_000

_SHORT = ["Our CI cache served stale builds twice last week."]
_MEDIUM = [
    "We run about 40 microservices and our deploy pipeline keeps failing on flaky integration tests.",
    "I spent most of Tuesday re-running jobs by hand because the retry logic ignores timeouts.",
    "We tried two other CI vendors but both priced us out once we passed 20 engineers.",
    "Right now a teammate babysits the queue with a shell script.",
]
_LONG = _MEDIUM * 4
_PARENT = (
    "Ask HN: What is the most annoying part of your build and deploy process?"
)

ITEMS = [
    {
        "comment_id": FIRST_ID + i,
        "comment": " ".join(sents),
        "parent": _PARENT,
        "story_title": _PARENT,
        "thread_type": "ask_hn",
        "sentences": list(sents),
    }
    for i, sents in enumerate((_SHORT, _MEDIUM, _LONG))
]


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def parse_sets(spec: str) -> list[tuple[str, int]]:
    """"screen@1,facets@1" -> [("screen", 1), ("facets", 1)]."""
    out = []
    for part in spec.split(","):
        name, sep, ver = part.strip().partition("@")
        if not sep or not ver.isdigit():
            raise ValueError(
                f"{part!r} needs a version: <name>@<int>, e.g. screen@1"
            )
        out.append((name, int(ver)))
    if not out:
        raise ValueError("empty --sets")
    return out


def _final_tokens(run_id, label: str, comment_id: int):
    """Measured input tokens for one (set, comment) final ledger row."""
    for row in read_rows(paths.ledger_path(run_id)):
        if (
            row.get("cost_class") in ("calculated", "unknown")
            and row.get("question_set") == label
            and row.get("comment_id") == comment_id
        ):
            return row.get("input_tokens")
    return None


def measure_tokens(
    sets: str, *, budget: str = "smoke", concurrency: int = 3, yes=False
) -> dict:
    """Measure input tokens for each set in `--sets` over ITEMS."""
    pairs = parse_sets(sets)
    question_sets = [load_question_set(n, v) for n, v in pairs]
    budgets = tomllib.loads(
        (paths.CONFIGS / "budgets.toml").read_text(encoding="utf-8")
    )
    if budget not in budget_names(budgets):
        raise SystemExit(
            f"unknown budget {budget!r} in {paths.CONFIGS / 'budgets.toml'}"
        )
    cap = budgets[budget]
    worst = budgets["worst_case_tokens_per_unknown_attempt"]
    usd_per_token = input_price(MODEL)
    price_version = next(
        r["version"]
        for r in tomllib.loads(
            (paths.CONFIGS / "prices.toml").read_text(encoding="utf-8")
        )["price"]
        if r["model"] == MODEL
    )

    estimates = [
        estimate_cost(ITEMS, qs, MODEL, {}, usd_per_input_token=usd_per_token)
        for qs in question_sets
    ]
    plan = {
        "budget": budget,
        "sets": [qs.label for qs in question_sets],
        "calls": len(question_sets) * len(ITEMS),
        "est_usd": round(sum(e["est_usd"] for e in estimates), 6),
    }
    print(json.dumps(plan, indent=1))
    if not yes:
        return {**plan, "dispatched": False}

    run_id = "measure-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    guard = BudgetGuard.for_budget(budget, cap, usd_per_token, worst)
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
            price_version=price_version,
            run_dir=paths.run_dir(run_id),
            concurrency=concurrency,
            budget=budget,
        )

        async def _all() -> dict:
            outs = {}
            async with client:
                for qs in question_sets:
                    out = await run_batch(ctx, [dict(i) for i in ITEMS], qs)
                    outs[qs.label] = out
                    print(
                        qs.label,
                        json.dumps(
                            {
                                k: out[k]
                                for k in (
                                    "completed",
                                    "failed",
                                    "new_requests",
                                    "cache_hits",
                                )
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
            return outs

        outs = asyncio.run(_all())
    finally:
        guard.close()

    tokens = {
        qs.label: [
            _final_tokens(run_id, qs.label, it["comment_id"]) for it in ITEMS
        ]
        for qs in question_sets
    }
    print(f"{'set':12} {'short':>7} {'medium':>7} {'long':>7}")
    for label, toks in tokens.items():
        print(f"{label:12} {toks[0]!s:>7} {toks[1]!s:>7} {toks[2]!s:>7}")
    summary = summarize(paths.ledger_path(run_id))
    print(
        "run",
        run_id,
        "calculated_usd",
        round(summary["calculated_usd"], 6),
        "unknown",
        summary["unknown_attempts"],
        "attempts",
        summary["attempts"],
    )
    return {
        **plan,
        "dispatched": True,
        "run_id": run_id,
        "tokens": tokens,
        "runs": outs,
        "ledger": summary,
    }

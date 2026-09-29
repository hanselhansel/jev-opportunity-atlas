"""Benchmark runner: screen@1, packed screen, facets@2, and two-level card
assignment over the invented cases in ``configs/benchmark/cases.<v>.yaml``.

Everything shares one run directory. Every estimate is printed before any
dispatch; without ``yes`` nothing is written and no request is made.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from atlas import paths
from atlas.cards.engine import assign
from atlas.cards.engine.cardset import load_cardset
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.questions import load_question_set
from atlas.inference.runner import RunContext
from atlas.pilot import packed, stages
from atlas.sources.htmltext import split_sentences

FACETS = ("workaround", "paid", "switched", "resolution")
CARDSET = ("pilot", "t1")
PACK_K = 5


def cases_path(version: str = "v1") -> Path:
    return paths.CONFIGS / "benchmark" / f"cases.{version}.yaml"


def load_cases(version: str = "v1") -> list[dict]:
    data = yaml.safe_load(cases_path(version).read_text(encoding="utf-8"))
    return list(data["cases"])


def cases_sha256(version: str = "v1") -> str:
    return hashlib.sha256(cases_path(version).read_bytes()).hexdigest()


def _sentences(text: str) -> list[str]:
    return split_sentences(text) or [text]


def case_items(cases: list[dict]) -> list[dict]:
    """Runner items for the screen/facets question sets."""
    return [
        {
            "comment_id": int(c["id"]),
            "comment": c["text"],
            "parent": c.get("parent") or "",
            "story_title": "",
            "thread_type": "story",
            "sentences": _sentences(c["text"]),
        }
        for c in cases
    ]


def facet_cases(cases: list[dict]) -> list[dict]:
    return [
        c
        for c in cases
        if any(f in c.get("expected", {}) for f in FACETS)
    ]


def card_cases(cases: list[dict]) -> list[dict]:
    return [c for c in cases if "card" in c.get("expected", {})]


def card_rows(cases: list[dict]) -> list[dict]:
    """Assignment rows: the whole case text is the pain sentence."""
    return [
        {
            "comment_id": int(c["id"]),
            "pain_sentence": c["text"],
            "sentences": _sentences(c["text"]),
        }
        for c in card_cases(cases)
    ]


def _card_estimates(rows: list[dict], cs, budget) -> list[dict]:
    """Level-1 estimate plus the level-2 worst case: every row charged the
    group with the most active cards. These items carry ``state`` and
    ``questions``, so they go through the bytes/3.2 path."""
    gqs = assign.engine_qs(
        "assign-g",
        cs,
        {"group": {"type": "choice", "instructions": assign.GROUP_INSTRUCTIONS}},
    )
    cqs = assign.engine_qs(
        "assign-c",
        cs,
        {"card": {"type": "choice", "instructions": assign.CARD_INSTRUCTIONS}},
    )
    biggest = max(
        (g for g in cs.groups if cs.cards_in(g)),
        key=lambda g: len(cs.cards_in(g)),
    )
    return [
        stages.estimate(
            [
                assign.group_item(
                    r["comment_id"], r["pain_sentence"], r["sentences"], cs
                )
                for r in rows
            ],
            gqs,
            budget,
        ),
        stages.estimate(
            [
                assign.card_item(
                    r["comment_id"],
                    r["pain_sentence"],
                    r["sentences"],
                    cs,
                    biggest,
                )
                for r in rows
            ],
            cqs,
            budget,
        ),
    ]


def _dispatch_cards(run_id, rows, cs, budget, run_dir):
    """Guard + client + RunContext exactly like ``stages.dispatch``, then the
    two-level assignment and the assignments parquet."""
    budgets, price_row, usd_per_token = stages.load_configs()
    cap, worst = stages.budget_cap(budgets, budget)
    guard = BudgetGuard.for_budget(budget, cap, usd_per_token, worst)
    try:
        client = JevClient(
            api_key=keys.get_api_key(),
            base=keys.base_url(),
            transport=stages._transport(),
        )
        ctx = RunContext(
            run_id=run_id,
            client=client,
            guard=guard,
            model=stages.MODEL,
            price_version=price_row["version"],
            run_dir=run_dir,
            budget=budget,
        )
        result = asyncio.run(assign.assign(ctx, rows, cs))
    finally:
        guard.close()
    assign.write_assignments(run_dir, result, cs.version)
    return {"assigned": len(result.rows)}


def run_benchmark(
    run_id, budget="discovery", yes=False, version="v1"
) -> dict:
    cases = load_cases(version)
    items = case_items(cases)
    fitems = case_items(facet_cases(cases))
    rows = card_rows(cases)
    cs = load_cardset(*CARDSET)
    qs_screen = load_question_set("screen", 1)
    packed_list, packed_map = packed.packed_items(items, k=PACK_K)
    qs_packed = packed.packed_question_set(PACK_K)
    qs_facets = load_question_set("facets", 2)

    estimates = [
        stages.estimate(items, qs_screen, budget),
        stages.estimate(packed_list, qs_packed, budget),
        stages.estimate(fitems, qs_facets, budget),
    ]
    if rows:
        estimates += _card_estimates(rows, cs, budget)
    for est in estimates:
        stages.print_estimate(est)
    total = sum(e["usd"] for e in estimates)
    print(f"total_usd={total:.6f}")
    if not yes:
        return {
            "estimates": estimates,
            "total_usd": total,
            "dispatched": False,
        }

    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    runs = {"screen": stages.dispatch(run_id, items, qs_screen, budget)}
    pq.write_table(packed_map, run_dir / "packed_map.parquet")
    runs["packed"] = stages.dispatch(run_id, packed_list, qs_packed, budget)
    runs["facets"] = stages.dispatch(run_id, fitems, qs_facets, budget)
    if rows:
        runs["cards"] = _dispatch_cards(run_id, rows, cs, budget, run_dir)
    meta = {
        "cases_version": version,
        "cases_sha256": cases_sha256(version),
        "n_cases": len(cases),
        "cardset": f"{CARDSET[0]}.{CARDSET[1]}",
        "pack_k": PACK_K,
        "budget": budget,
    }
    (run_dir / "benchmark.json").write_text(
        json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "estimates": estimates,
        "total_usd": total,
        "dispatched": True,
        "runs": runs,
    }

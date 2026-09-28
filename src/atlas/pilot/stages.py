"""Pilot stages: screen and facets, plus the helpers the other pilot stages
reuse — configs, the bytes/3.2 cost estimate, and one guarded dispatch.

Every stage prints an estimate and writes nothing unless ``yes`` is given.
Screen and facets share the base run directory so one run_manifest/ledger
covers the whole pilot.
"""

from __future__ import annotations

import asyncio
import json
import math
import tomllib

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.questions import (
    build_state,
    canonical_json,
    load_question_set,
    questions_for,
)
from atlas.inference.runner import RunContext, run_batch

MODEL = "jev-1.13.0"

FACET_SELECTION = pa.schema(
    [
        ("comment_id", pa.int64()),
        ("screen_p", pa.float64()),
        ("rule", pa.string()),
        ("selection_prob", pa.float64()),
    ]
)


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def load_configs():
    """(budgets, price_row, usd_per_input_token) for MODEL."""
    budgets = tomllib.loads(
        (paths.CONFIGS / "budgets.toml").read_text(encoding="utf-8")
    )
    prices = tomllib.loads(
        (paths.CONFIGS / "prices.toml").read_text(encoding="utf-8")
    )
    price_row = next(r for r in prices["price"] if r["model"] == MODEL)
    return budgets, price_row, price_row["input_usd_per_million"] / 1e6


def budget_cap(budgets, name):
    """(cap_usd, worst_case_tokens) for a named budget; unknown names exit."""
    if name not in budgets or name.startswith("worst_case"):
        raise SystemExit(
            f"unknown budget {name!r} in {paths.CONFIGS / 'budgets.toml'}"
        )
    return budgets[name], budgets["worst_case_tokens_per_unknown_attempt"]


def item_tokens(item: dict, qs) -> int:
    """Estimated input tokens for one item, matching the body runner._process
    sends; bytes / 3.2 until the L9 estimator lands."""
    sentences = item.get("sentences") or []
    if "state" in item:
        state = item["state"]
    else:
        state = build_state(
            comment=item["comment"],
            parent=item.get("parent"),
            story_title=item.get("story_title"),
            thread_type=item.get("thread_type"),
            sentences=sentences,
            fields=qs.state_fields,
            parent_limit=qs.parent_limit,
        )
    questions = (
        item["questions"]
        if "questions" in item
        else questions_for(qs, sentences)
    )
    body = {"state": state, "model": MODEL, "questions": questions}
    return math.ceil(len(canonical_json(body).encode("utf-8")) / 3.2)


def estimate(items, qs, budget) -> dict:
    budgets, _price_row, usd_per_token = load_configs()
    cap, _worst = budget_cap(budgets, budget)
    tokens = sum(item_tokens(item, qs) for item in items)
    return {
        "question_set": qs.label,
        "calls": len(items),
        "input_tokens": tokens,
        "usd": tokens * usd_per_token,
        "budget": budget,
        "cap_usd": cap,
    }


def budget_headroom(budget="pilot") -> dict:
    """Committed and remaining USD for `budget` and for the whole account.

    Committed per name = calculated_usd + unknown_attempts *
    worst_case_tokens_per_unknown_attempt * usd_per_input_token, matching the
    guard's rebuild-from-disk rule; account = sum over every budget name
    found in runs/*/run_manifest.json.
    """
    from atlas.inference.ledger import summarize

    budgets, _price_row, usd_per_token = load_configs()
    cap, worst = budget_cap(budgets, budget)
    committed: dict[str, float] = {}
    for manifest in sorted(paths.RUNS.glob("*/run_manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"unreadable run manifest {manifest}: {exc}"
            ) from exc
        ledger_path = manifest.parent / "ledger.jsonl"
        if not ledger_path.exists():
            continue
        s = summarize(ledger_path)
        name = data.get("budget") or "<none>"
        committed[name] = committed.get(name, 0.0) + (
            s["calculated_usd"]
            + s["unknown_attempts"] * worst * usd_per_token
        )
    mine = committed.get(budget, 0.0)
    account = sum(committed.values())
    total = budgets.get("account_total")
    return {
        "budget": budget,
        "cap_usd": cap,
        "committed_usd": mine,
        "remaining_usd": cap - mine,
        "account_total": total,
        "account_committed_usd": account,
        "account_remaining_usd": (
            total - account if total is not None else None
        ),
    }


def print_estimate(est) -> None:
    print(json.dumps(est, indent=1))


def dispatch(run_id, items, qs, budget, concurrency=8) -> dict:
    """Guard + client + RunContext, then run_batch; the guard always closes."""
    budgets, price_row, usd_per_token = load_configs()
    cap, worst = budget_cap(budgets, budget)
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
            price_version=price_row["version"],
            run_dir=paths.run_dir(run_id),
            concurrency=concurrency,
            budget=budget,
        )
        return asyncio.run(run_batch(ctx, items, qs))
    finally:
        guard.close()


def pilot_items(sample_id):
    """(frame_snapshot_id, load_items dicts in draw order) for a sample."""
    from atlas.sources.items import load_items

    meta = json.loads(
        (paths.SAMPLES / f"{sample_id}.json").read_text(encoding="utf-8")
    )
    snapshot_id = meta["frame_snapshot_id"]
    table = pq.read_table(paths.sample_path(sample_id))
    order = np.argsort(
        table.column("draw_order").to_numpy(zero_copy_only=False), kind="stable"
    )
    ids = table.column("comment_id").to_numpy(zero_copy_only=False)[order]
    items = load_items(
        paths.snapshot_dir(snapshot_id), [int(i) for i in ids]
    )
    return snapshot_id, items


def read_pilot_json(run_id) -> dict:
    path = paths.run_dir(run_id) / "pilot.json"
    if not path.exists():
        raise SystemExit(f"{path} missing; run the screen stage first")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_pilot_json(run, **fields) -> None:
    path = paths.run_dir(run) / "pilot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(
        json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_screen(sample_id, run_id, budget="pilot", yes=False) -> dict:
    """Screen every sampled comment with screen@1."""
    qs = load_question_set("screen", 1)
    snapshot_id, items = pilot_items(sample_id)
    est = estimate(items, qs, budget)
    print_estimate(est)
    if not yes:
        return {"estimate": est, "dispatched": False}
    _write_pilot_json(
        run_id, sample_id=sample_id, snapshot_id=snapshot_id, run_id=run_id
    )
    out = dispatch(run_id, items, qs, budget)
    return {"estimate": est, "dispatched": True, "run": out}


def _facet_selection(run_id, sampled, threshold, random_share, seed):
    """(selection rows, ids): gate on screen noul, plus a seeded random share
    of the below-gate rest so the pilot can measure what the gate drops."""
    from atlas.evaluation.queue import read_answers

    scores = {
        cid: a["noul"]
        for cid, a in read_answers(run_id, "firsthand_problem").items()
        if a["noul"] is not None
    }
    gate = sorted(c for c in sampled if c in scores and scores[c] >= threshold)
    rest = sorted(c for c in sampled if c in scores and scores[c] < threshold)
    k = round(random_share * len(rest))
    rng = np.random.default_rng(seed)
    picked = rng.choice(rest, k, replace=False) if k else []
    random_ids = sorted(int(c) for c in picked)
    prob = k / len(rest) if rest else 0.0
    rows = [
        {
            "comment_id": c,
            "screen_p": float(scores[c]),
            "rule": "gate",
            "selection_prob": 1.0,
        }
        for c in gate
    ] + [
        {
            "comment_id": c,
            "screen_p": float(scores[c]),
            "rule": "random",
            "selection_prob": prob,
        }
        for c in random_ids
    ]
    rows.sort(key=lambda r: r["comment_id"])
    return rows, [r["comment_id"] for r in rows]


def run_facets(
    run_id, threshold=0.3, random_share=0.10, seed=1, budget="pilot", yes=False
) -> dict:
    """Facets on screen-gated comments plus a seeded share of the rest."""
    from atlas.sources.items import load_items

    pilot = read_pilot_json(run_id)
    sample = pq.read_table(paths.sample_path(pilot["sample_id"]))
    sampled = [int(c) for c in sample.column("comment_id").to_pylist()]
    rows, selected = _facet_selection(
        run_id, sampled, threshold, random_share, seed
    )
    items = load_items(paths.snapshot_dir(pilot["snapshot_id"]), selected)
    qs = load_question_set("facets", 1)
    est = estimate(items, qs, budget)
    print_estimate(est)
    if not yes:
        return {"estimate": est, "dispatched": False}
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=FACET_SELECTION),
        run_dir / "facet_selection.parquet",
    )
    out = dispatch(run_id, items, qs, budget)
    return {"estimate": est, "dispatched": True, "run": out}

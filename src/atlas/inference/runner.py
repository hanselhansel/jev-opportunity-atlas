"""Batch runner: items -> ANSWERS parquet parts, with ledger, budget, cache, resume.

Order of operations per item: done-set skip -> cache replay -> per-attempt
reserve/settle through `on_attempt` with a `pending` ledger row before each send
and a final row after each response. A crash leaves a `pending` row that the
next run reconciles to `unknown` (never silently dropped). BudgetExceeded sets
`stopped="budget"`: no new sends, in-flight tasks drain, completed items flush.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from atlas import paths
from atlas.inference.budget import BudgetExceeded, BudgetGuard
from atlas.inference.cache import ResponseCache, cache_key
from atlas.inference.client import JevClient
from atlas.inference.ledger import Ledger, read_rows, unresolved_pending
from atlas.inference.questions import build_state, canonical_json, questions_for
from atlas.inference.runner_io import (
    answer_rows,
    append_done,
    ensure_manifest,
    load_done,
    write_part,
)


@dataclass
class RunContext:
    run_id: str
    client: JevClient
    guard: BudgetGuard
    model: str
    price_version: str
    run_dir: Path | None = None
    cache_path: Path | None = None
    concurrency: int = 8
    budget: str | None = None
    batch_items: int = 200

    def __post_init__(self):
        if self.run_dir is None:
            self.run_dir = paths.run_dir(self.run_id)
        if self.cache_path is None:
            self.cache_path = paths.CACHE / "jev.sqlite"
        if self.budget is None:
            self.budget = self.guard.name


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


async def run_batch(ctx: RunContext, items: Iterable[dict], qs) -> dict:
    t0 = time.monotonic()
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    ensure_manifest(ctx, qs)
    ledger_path = ctx.run_dir / "ledger.jsonl"
    ledger = Ledger(ledger_path)
    cache = ResponseCache(ctx.cache_path)
    out = {
        "completed": 0,
        "failed": 0,
        "skipped_completed": 0,
        "cache_hits": 0,
        "new_requests": 0,
        "stopped": None,
    }
    try:
        for row in unresolved_pending(read_rows(ledger_path)):
            ledger.append(
                {
                    **row,
                    "cost_class": "unknown",
                    "cost_usd": None,
                    "validation": "not_attempted",
                },
                sync=True,
            )
        done = load_done(ctx.run_dir, qs.label)
        if ctx.client.is_open:
            await _consume(ctx, items, qs, ledger, cache, done, out)
        else:
            async with ctx.client:
                await _consume(ctx, items, qs, ledger, cache, done, out)
    finally:
        ledger.close()
        cache.close()
    out["wall_s"] = time.monotonic() - t0
    return out


async def _consume(ctx, items, qs, ledger, cache, done, out) -> None:
    sem = asyncio.Semaphore(ctx.concurrency)
    it = iter(items)
    while True:
        chunk = list(itertools.islice(it, ctx.batch_items))
        if not chunk:
            return
        rows, done_ids = [], []
        tasks = []
        for item in chunk:
            if item["comment_id"] in done:
                out["skipped_completed"] += 1
                continue
            tasks.append(
                asyncio.create_task(
                    _process(ctx, item, qs, ledger, cache, sem, out, rows, done_ids)
                )
            )
        await _gather(tasks)
        if rows:
            seq = write_part(ctx.run_dir, rows)
            append_done(
                ctx.run_dir,
                [
                    {"comment_id": cid, "question_set": qs.label, "part": seq}
                    for cid in done_ids
                ],
            )
            done.update(done_ids)
        if out["stopped"]:
            return


async def _gather(tasks: list) -> None:
    """Wait for all tasks; on the first exception cancel the rest, drain them,
    and re-raise that original exception (never an ExceptionGroup)."""
    if not tasks:
        return
    done_set, pending = await asyncio.wait(
        tasks, return_when=asyncio.FIRST_EXCEPTION
    )
    exc = next(
        (
            t.exception()
            for t in tasks
            if t in done_set and not t.cancelled() and t.exception() is not None
        ),
        None,
    )
    if exc is None:
        return
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    raise exc


def _base_row(ctx, qs, comment_id, key, logical_call_id, queue_ms) -> dict:
    return {
        "run_id": ctx.run_id,
        "logical_call_id": logical_call_id,
        "comment_id": comment_id,
        "question_set": qs.label,
        "question_count": len(qs.questions),
        "input_hash": key,
        "model_requested": ctx.model,
        "queue_ms": queue_ms,
        "price_version": ctx.price_version,
    }


def _replay_row(ctx, qs, cid, key, logical_call_id, hit, queue_ms) -> dict:
    return {
        **_base_row(ctx, qs, cid, key, logical_call_id, queue_ms),
        "attempt": 0,
        "started_at": _utcnow(),
        "ended_at": _utcnow(),
        "request_ms": 0.0,
        "backoff_ms": 0.0,
        "request_id": hit["request_id"],
        "model_returned": hit["response"].get("model"),
        "input_tokens": hit["input_tokens"],
        "cache": "hit",
        "cost_class": "replay",
        "cost_usd": 0.0,
    }


def _final_row(ctx, qs, cid, key, logical_call_id, queue_ms, a) -> dict:
    known = a.charge_known
    return {
        **_base_row(ctx, qs, cid, key, logical_call_id, queue_ms),
        "attempt": a.attempt,
        "model_returned": a.model_returned,
        "request_id": a.request_id,
        "started_at": a.started_at,
        "ended_at": a.ended_at,
        "request_ms": a.request_ms,
        "backoff_ms": a.backoff_ms,
        "http_status": a.http_status,
        "error_type": a.error_type,
        "validation": a.validation,
        "input_tokens": a.input_tokens,
        "output_tokens": a.output_tokens,
        "cache": "miss",
        "cost_class": "calculated" if known else "unknown",
        "cost_usd": (a.input_tokens or 0) * ctx.guard.usd_per_input_token
        if known
        else None,
    }


async def _process(ctx, item, qs, ledger, cache, sem, out, rows, done_ids) -> None:
    cid = item["comment_id"]
    created = time.monotonic()
    async with sem:
        queue_ms = (time.monotonic() - created) * 1000.0
        if out["stopped"]:
            return
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
            item["questions"] if "questions" in item else questions_for(qs, sentences)
        )
        key = cache_key(state, questions, qs.label, ctx.model)
        logical_call_id = f"{qs.label}:{cid}:{uuid4().hex[:12]}"
        hit = cache.get(key)
        if hit is not None:
            ledger.append(_replay_row(ctx, qs, cid, key, logical_call_id, hit, queue_ms))
            rows.extend(
                answer_rows(
                    ctx.run_id,
                    cid,
                    qs.label,
                    questions,
                    hit["response"]["answers"],
                    hit["response"].get("model"),
                    hit["request_id"],
                    logical_call_id,
                    True,
                )
            )
            done_ids.append(cid)
            out["cache_hits"] += 1
            out["completed"] += 1
            return
        body = {"state": state, "model": ctx.model, "questions": questions}
        est = math.ceil(len(canonical_json(body).encode("utf-8")) / 3.2)
        handle = None

        async def on_attempt(event):
            nonlocal handle
            if event.phase == "before_send":
                handle = await ctx.guard.reserve(est)
                ledger.append(
                    {
                        **_base_row(ctx, qs, cid, key, logical_call_id, queue_ms),
                        "attempt": event.attempt_no,
                        "started_at": _utcnow(),
                        "cache": "miss",
                        "cost_class": "pending",
                    },
                    sync=True,
                )
                out["new_requests"] += 1
            else:
                await ctx.guard.settle(handle, event.attempt.input_tokens,
                                       event.attempt.charge_known)
                ledger.append(
                    _final_row(ctx, qs, cid, key, logical_call_id, queue_ms,
                               event.attempt),
                    sync=True,
                )

        try:
            res = await ctx.client.evaluate(
                state, questions, ctx.model, on_attempt=on_attempt
            )
        except BudgetExceeded:
            out["stopped"] = "budget"
            return
        except BaseException:
            # Propagate the crash, and stop peers that acquire the semaphore in
            # the window before gather cancels them.
            out["stopped"] = "error"
            raise
        if res.ok:
            last = res.attempts[-1]
            cache.put(
                key,
                {"model": res.model_returned, "answers": res.answers},
                run_id=ctx.run_id,
                logical_call_id=logical_call_id,
                request_id=last.request_id,
                input_tokens=last.input_tokens,
            )
            rows.extend(
                answer_rows(
                    ctx.run_id,
                    cid,
                    qs.label,
                    questions,
                    res.answers,
                    res.model_returned,
                    last.request_id,
                    logical_call_id,
                    False,
                )
            )
            done_ids.append(cid)
            out["completed"] += 1
        else:
            out["failed"] += 1

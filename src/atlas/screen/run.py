"""Streaming packed screen over a whole sample (L17 17.3).

Every sampled comment is screened k-at-a-time through the packed question set.
Comment ids are sorted, sliced into `chunk`-sized pieces (a multiple of k, so
packing groups are globally consecutive), loaded chunk by chunk, and sent
through `run_batch`. `packed_map.parquet/` grows by one part per chunk, written
before the chunk's calls so a crash never loses the id mapping. Resume skips
completed packed ids via done.jsonl and never rewrites earlier map parts.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.inference import keys, runner_io
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.runner import RunContext, run_batch
from atlas.pilot import packed, stages

RPM_CAP = 1200  # TypeSafe documented requests-per-minute ceiling
PROBE_MAX = 2000


def _report(progress: dict) -> None:
    print(json.dumps({"progress": progress}, sort_keys=True))


def _write_json(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _write_map_part(map_dir: Path, index: int, table: pa.Table) -> None:
    """One packed-map part per chunk. Existing parts must match this run's
    packing byte-for-row; they are verified, never rewritten."""
    part = map_dir / f"part-{index:05d}.parquet"
    if part.exists():
        if not pq.read_table(part).equals(table):
            raise RuntimeError(
                f"{part}: stored packed map differs from this run's packing; "
                "the sample or chunking changed under an existing run"
            )
        return
    map_dir.mkdir(parents=True, exist_ok=True)
    # Dot prefix: pyarrow dataset discovery skips it, so a crash leftover is
    # never read as a map part.
    tmp = part.with_name("." + part.name + ".tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, part)


class _LedgerSpend:
    """Cumulative calculated USD from ledger.jsonl, read incrementally."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.usd = 0.0

    def poll(self) -> float:
        if not self.path.exists():
            return self.usd
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            data = fh.read()
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            return self.usd
        self.offset += last_nl + 1
        for line in data[: last_nl + 1].splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("cost_class") == "calculated":
                self.usd += row.get("cost_usd") or 0.0
        return self.usd


async def _dispatch_chunks(ctx, ids, snapdir, k, chunk, qs, total_calls):
    """One run_batch per chunk with map parts written first and progress after."""
    from atlas.sources.items import load_items

    run_dir = ctx.run_dir
    map_dir = run_dir / "packed_map.parquet"
    totals = {
        "completed": 0,
        "failed": 0,
        "skipped_completed": 0,
        "cache_hits": 0,
        "new_requests": 0,
        "wall_s": 0.0,
    }
    n_chunks = math.ceil(len(ids) / chunk)
    spend = _LedgerSpend(run_dir / "ledger.jsonl")
    comments_done = 0
    stopped = None
    t0 = time.monotonic()
    for i in range(n_chunks):
        chunk_ids = ids[i * chunk : (i + 1) * chunk]
        items = load_items(snapdir, [int(c) for c in chunk_ids])
        packed_list, pmap = packed.packed_items(items, k)
        _write_map_part(map_dir, i, pmap)
        out = await run_batch(ctx, packed_list, qs)
        for key in totals:
            totals[key] += out[key]
        comments_done += len(chunk_ids)
        stopped = out["stopped"]
        done_total = len(runner_io.load_done(run_dir, qs.label))
        elapsed_min = (time.monotonic() - t0) / 60.0
        calls_per_min = totals["new_requests"] / elapsed_min if elapsed_min else 0.0
        remaining = max(0, total_calls - done_total)
        _report(
            {
                "chunk": i,
                "chunks": n_chunks,
                "comments_done": comments_done,
                "calls": totals["new_requests"],
                "calls_total_done": done_total,
                "usd_calculated": spend.poll(),
                "calls_per_min": calls_per_min,
                "eta_min": (
                    remaining / calls_per_min if calls_per_min > 0 else None
                ),
            }
        )
        if stopped == "budget":
            break
    return totals, stopped


def screen_sample(
    sample_id,
    run_id,
    k=5,
    budget="screen",
    rpm=1000,
    chunk=5000,
    yes=False,
    concurrency=32,
) -> dict:
    """Screen every comment in `sample_id` packed k per call into `run_id`."""
    if chunk % k != 0:
        raise ValueError(f"chunk {chunk} must be a multiple of k {k}")
    if not 0 < rpm <= RPM_CAP:
        raise ValueError(f"rpm {rpm} outside (0, {RPM_CAP}]")

    from atlas.sources.items import load_items

    meta = json.loads((paths.SAMPLES / f"{sample_id}.json").read_text())
    snapshot_id = meta["frame_snapshot_id"]
    sample = pq.read_table(
        paths.sample_path(sample_id), columns=["comment_id"]
    )
    ids = np.sort(
        sample.column("comment_id").to_numpy(zero_copy_only=False)
    ).astype(np.int64)
    n = len(ids)
    snapdir = paths.snapshot_dir(snapshot_id)
    run_dir = paths.run_dir(run_id)
    qs = packed.packed_question_set(k)
    total_calls = math.ceil(n / k)

    params = {
        "sample_id": sample_id,
        "snapshot_id": snapshot_id,
        "k": k,
        "chunk": chunk,
        "n_comments": n,
        "question_set": packed.PACKED_LABEL,
    }
    params_path = run_dir / "screen.json"
    if params_path.exists():
        existing = json.loads(params_path.read_text(encoding="utf-8"))
        if existing != params:
            raise SystemExit(
                f"{params_path}: stored params {existing} differ from "
                f"{params}; resume with the same arguments"
            )

    # Estimate from an evenly spaced probe; full comment text is never loaded.
    budgets, price_row, usd_per_token = stages.load_configs()
    cap, worst = stages.budget_cap(budgets, budget)
    probe_ids = np.unique(
        ids[np.linspace(0, n - 1, min(n, PROBE_MAX)).astype(np.int64)]
    )
    probe_items = load_items(snapdir, [int(c) for c in probe_ids])
    probe_packed, _ = packed.packed_items(probe_items, k)
    mean_tokens = (
        sum(stages.item_tokens(p, qs) for p in probe_packed) / len(probe_packed)
        if probe_packed
        else 0.0
    )
    done = (
        runner_io.load_done(run_dir, packed.PACKED_LABEL)
        if run_dir.exists()
        else set()
    )
    remaining_calls = sum(
        1 for pid in ids[::k] if int(pid) not in done
    )
    input_tokens = int(mean_tokens * remaining_calls)
    head = stages.budget_headroom(budget)
    est = {
        "question_set": packed.PACKED_LABEL,
        "comments": n,
        "k": k,
        "calls": total_calls,
        "remaining_calls": remaining_calls,
        "input_tokens": input_tokens,
        "usd": input_tokens * usd_per_token,
        "budget": budget,
        "cap_usd": cap,
        "method": f"bytes/3.2 probe n={len(probe_ids)}",
        "remaining_usd": head["remaining_usd"],
        "account_remaining_usd": head["account_remaining_usd"],
    }
    stages.print_estimate(est)
    if not yes:
        return {"estimate": est, "dispatched": False}

    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(params_path, params)
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
            concurrency=concurrency,
            budget=budget,
            rpm=rpm,
        )
        totals, stopped = asyncio.run(
            _dispatch_chunks(ctx, ids, snapdir, k, chunk, qs, total_calls)
        )
    finally:
        guard.close()
    return {
        "estimate": est,
        "dispatched": True,
        "run": totals,
        "stopped": stopped,
    }

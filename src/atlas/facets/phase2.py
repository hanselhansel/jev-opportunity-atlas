"""Two-phase facet sample and run (L22).

Phase 2 draws within each v2 stratum of the main screen table
(`screen_by_comment.parquet`):
- positives (``firsthand_p >= cutoff``): ``n2_h`` proportional to the
  stratum's phase-1 weighted count, capped at the stratum's size with the
  shortfall redistributed to the remaining strata, ``n_pos`` total;
- a check sample of below-cutoff comments, ``n_neg`` total, allocated the
  same way.
Every row keeps the phase-1 weight ``w1`` and the phase-2 selection
probability ``p2``; the final weight is ``w1 / p2``. ``run_phase2`` sends
the drawn comments through facets@2 in chunks, rate-limited, under the
facets budget; a rerun resumes via the runner's done set.

Ported from the main run's phase-2 script (see docs/runbook-main-run.md).
"""

from __future__ import annotations

import asyncio
import json
import math
import os

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths

PHASE2_SCHEMA = pa.schema(
    [
        ("comment_id", pa.int64()),
        ("story_id", pa.int64()),
        ("stratum", pa.string()),
        ("half", pa.string()),
        ("phase", pa.string()),
        ("w1", pa.float64()),
        ("p2", pa.float64()),
        ("weight", pa.float64()),
        ("firsthand_p", pa.float64()),
    ]
)

QUESTION_SET = ("facets", 2)
RPM_CAP = 1200  # TypeSafe documented requests-per-minute ceiling
PROBE_MAX = 2000


def allocate_capped(
    wsum: dict[str, float], sizes: dict[str, int], n_total: int
) -> dict[str, int]:
    """Allocate ``n_total`` across strata proportional to ``wsum``, each
    stratum capped at ``sizes``.

    Strata whose share exceeds their size are capped; the shortfall is
    redistributed to the remaining open strata until the total is met or
    every stratum is capped. Counts round with ``max(1, round())``.
    """
    alloc, open_h, left = {}, set(sizes), n_total
    while left > 0 and open_h:
        tot = sum(wsum[h] for h in open_h)
        share = {h: left * wsum[h] / tot for h in open_h}
        capped = {
            h for h in open_h if alloc.get(h, 0) + share[h] >= sizes[h]
        }
        if capped:
            for h in capped:
                left -= sizes[h] - alloc.get(h, 0)
                alloc[h] = sizes[h]
            open_h -= capped
            continue
        for h in open_h:
            alloc[h] = alloc.get(h, 0) + share[h]
        left = 0
    return {h: max(1, round(a)) for h, a in alloc.items()}


def draw_phase2(
    screen_run: str,
    sample_id: str,
    *,
    n_pos: int = 28_000,
    n_neg: int = 2_000,
    cutoff: float = 0.7,
    seed: int,
    snapshot_id: str,
) -> pa.Table:
    """Draw the phase-2 facet sample from a screen run's by-comment table."""
    t = pq.read_table(
        paths.run_dir(screen_run) / "screen_by_comment.parquet"
    ).to_pylist()
    rng = np.random.default_rng(seed)
    out = []
    for kind, n_total, keep in (
        ("pos", n_pos, lambda p: p >= cutoff),
        ("neg", n_neg, lambda p: p < cutoff),
    ):
        rows = [r for r in t if keep(r["firsthand_p"])]
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r["stratum"], []).append(r)
        wsum = {h: sum(r["weight"] for r in rs) for h, rs in by.items()}
        alloc = allocate_capped(
            wsum, {h: len(rs) for h, rs in by.items()}, n_total
        )
        for h in sorted(by):
            rs = sorted(by[h], key=lambda r: r["comment_id"])
            n2 = min(len(rs), alloc[h])
            idx = rng.choice(len(rs), n2, replace=False)
            p2 = n2 / len(rs)
            for i in sorted(idx):
                r = rs[i]
                out.append(
                    {
                        "comment_id": r["comment_id"],
                        "story_id": r["story_id"],
                        "stratum": r["stratum"],
                        "half": r["half"],
                        "phase": kind,
                        "w1": r["weight"],
                        "p2": p2,
                        "weight": r["weight"] / p2,
                        "firsthand_p": r["firsthand_p"],
                    }
                )
    tbl = pa.Table.from_pylist(out, schema=PHASE2_SCHEMA)
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    pq.write_table(tbl, paths.SAMPLES / f"{sample_id}.parquet")
    (paths.SAMPLES / f"{sample_id}.json").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "seed": seed,
                "parent_run": screen_run,
                "cutoff": cutoff,
                "n_pos": sum(r["phase"] == "pos" for r in out),
                "n_neg": sum(r["phase"] == "neg" for r in out),
                "snapshot_id": snapshot_id,
                "design": (
                    "two-phase: phase 1 stratified screen sample; phase 2 "
                    "stratified SRSWOR within v2 strata, n2_h proportional "
                    "to phase-1 weighted count; final weight w1/p2"
                ),
            },
            indent=1,
        )
        + "\n"
    )
    return tbl


def estimate_phase2(
    sample_id: str, qs=None, probe_max: int = PROBE_MAX
) -> dict:
    """Cost of running `qs` (default facets@2) over the whole sample,
    extrapolated from an evenly spaced probe."""
    from atlas.inference.estimate import estimate_cost
    from atlas.inference.questions import load_question_set
    from atlas.pilot.stages import MODEL
    from atlas.sources.items import load_items

    meta = json.loads((paths.SAMPLES / f"{sample_id}.json").read_text())
    ids = (
        pq.read_table(
            paths.sample_path(sample_id), columns=["comment_id"]
        )
        .column("comment_id")
        .to_pylist()
    )
    qs = qs if qs is not None else load_question_set(*QUESTION_SET)
    probe = load_items(
        paths.snapshot_dir(meta["snapshot_id"]),
        ids[:: max(1, len(ids) // probe_max)],
    )
    est = estimate_cost(probe, qs, MODEL, {})
    scale = len(ids) / len(probe) if probe else 0.0
    return {
        "question_set": qs.label,
        "calls": len(ids),
        "est_usd": round(est["est_usd"] * scale, 3),
        "probe": len(probe),
    }


def _write_json(path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _pin_params(run_dir, sample_id: str, snapshot_id: str, ids) -> dict:
    """Check ``sample_id`` against the run's pinned sample (``facets.json``).

    The first dispatched run pins the sample it started with. A later run
    may pass the same sample or one whose comment-id set is a superset of
    the pinned one (a second-wave expansion); anything else is refused so
    answers from unrelated samples never mix in one run dir. Returns the
    params to (re)write on dispatch.
    """
    path = run_dir / "facets.json"
    if not path.exists():
        return {"sample_id": sample_id, "snapshot_id": snapshot_id}
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("snapshot_id") != snapshot_id:
        raise SystemExit(
            f"{path}: snapshot {stored.get('snapshot_id')!r} != "
            f"{snapshot_id!r}; refusing to mix runs"
        )
    pinned = stored["sample_id"]
    if pinned == sample_id:
        return stored
    pinned_path = paths.sample_path(pinned)
    if not pinned_path.exists():
        raise SystemExit(
            f"{path}: pinned sample {pinned!r} is missing; cannot verify "
            f"that {sample_id!r} extends it"
        )
    pinned_ids = set(
        pq.read_table(pinned_path, columns=["comment_id"])
        .column("comment_id")
        .to_pylist()
    )
    if not pinned_ids <= set(ids):
        raise SystemExit(
            f"{path}: sample {sample_id!r} is not a superset of pinned "
            f"sample {pinned!r}; refusing to mix samples in one run"
        )
    stored["previous_sample_ids"] = [
        *stored.get("previous_sample_ids", []),
        pinned,
    ]
    stored["sample_id"] = sample_id
    return stored


def _report(n: int, out: dict) -> None:
    print(f"chunk {n}: {out}", flush=True)


async def _dispatch_chunks(ctx, ids, snapdir, qs, chunk: int):
    """One run_batch per chunk of comments; stop early on budget/error."""
    from atlas.inference.runner import run_batch
    from atlas.sources.items import load_items

    totals = {
        "completed": 0,
        "failed": 0,
        "skipped_completed": 0,
        "cache_hits": 0,
        "new_requests": 0,
        "wall_s": 0.0,
    }
    stopped = None
    n_chunks = math.ceil(len(ids) / chunk) if ids else 0
    async with ctx.client:
        for n in range(n_chunks):
            items = load_items(snapdir, ids[n * chunk : (n + 1) * chunk])
            out = await run_batch(ctx, items, qs)
            for key in totals:
                totals[key] += out[key]
            _report(n, out)
            stopped = out["stopped"]
            if stopped:
                break
    return totals, stopped


def run_phase2(
    sample_id: str,
    run_id: str,
    *,
    budget: str = "facets",
    rpm: float | None = 1000.0,
    chunk: int = 5000,
    concurrency: int = 8,
    yes: bool = False,
) -> dict:
    """Run facets@2 over the phase-2 sample; estimate first, dispatch on
    ``yes`` only. `rpm=None` disables pacing."""
    from atlas.inference import keys
    from atlas.inference.budget import BudgetGuard
    from atlas.inference.client import JevClient
    from atlas.inference.questions import load_question_set
    from atlas.inference.runner import BudgetStopped, RunContext
    from atlas.pilot import stages

    if rpm is not None and not 0 < rpm <= RPM_CAP:
        raise ValueError(f"rpm {rpm} outside (0, {RPM_CAP}]")
    if chunk <= 0:
        raise ValueError(f"chunk must be > 0, got {chunk}")

    meta = json.loads((paths.SAMPLES / f"{sample_id}.json").read_text())
    ids = (
        pq.read_table(
            paths.sample_path(sample_id), columns=["comment_id"]
        )
        .column("comment_id")
        .to_pylist()
    )
    qs = load_question_set(*QUESTION_SET)
    run_dir = paths.run_dir(run_id)
    params = _pin_params(run_dir, sample_id, meta["snapshot_id"], ids)
    est = estimate_phase2(sample_id, qs=qs)
    stages.print_estimate(est)
    if not yes:
        return {"estimate": est, "dispatched": False}

    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "facets.json", params)
    budgets, price_row, per_token = stages.load_configs()
    cap, worst = stages.budget_cap(budgets, budget)
    guard = BudgetGuard.for_budget(budget, cap, per_token, worst)
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
            _dispatch_chunks(
                ctx, ids, paths.snapshot_dir(meta["snapshot_id"]), qs, chunk
            )
        )
    finally:
        guard.close()
    if stopped:
        done = totals["completed"] + totals["skipped_completed"]
        BudgetStopped(
            budget, done, max(0, len(ids) - done - totals["failed"]), stopped
        ).fail()
    return {
        "estimate": est,
        "dispatched": True,
        "run": totals,
        "stopped": stopped,
    }

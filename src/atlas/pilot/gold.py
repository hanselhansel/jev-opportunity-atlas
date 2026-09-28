"""Pilot label queues and gold-draw records.

`build_calibration` writes the same calibration queue `atlas label run
--label-set calibration` would build, so that command later just reuses it.
The audit queue is a seeded draw of comments that received facet answers, for
the deep-facet audit. Both queues regenerate contract GOLD_DRAWS rows on every
call, so later top-ups are captured; rows of other label sets are never
touched, and reruns are idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.evaluation.queue import (
    DEFAULT_BAND_SIZES,
    DEFAULT_BANDS,
    build_queue,
    domain_subset,
    labeling_frame,
    load_queue,
    queue_path,
    save_queue,
)
from atlas.pilot import stages

AUDIT_N = 50
GOLD_FILE = "gold_draws.parquet"


def _other_queue_ids(skip: Path) -> set[int]:
    """Ids in every queue file except `skip` (same convention as label run)."""
    directory = paths.LABELS / "queues"
    ids: set[int] = set()
    if directory.is_dir():
        for file in sorted(directory.glob("*.json")):
            if file != skip:
                ids.update(load_queue(file).get("ids", []))
    return ids


def _faceted(run_id) -> set[int]:
    """Comment ids with at least one facets@1 answer row in the run."""
    directory = paths.run_dir(run_id) / "answers"
    out: set[int] = set()
    if directory.is_dir():
        for file in sorted(directory.glob("*.parquet")):
            t = pq.read_table(file, columns=["comment_id", "question_set"])
            t = t.filter(pc.equal(t.column("question_set"), "facets@1"))
            out.update(int(c) for c in t.column("comment_id").to_pylist())
    return out


def _queue_meta(run_id, sample_id, question_id) -> dict:
    return {
        "snapshot_id": stages.read_pilot_json(run_id)["snapshot_id"],
        "sample_id": sample_id,
        "run_id": run_id,
        "question_id": question_id,
        "created_at": datetime.now(UTC).isoformat(),
        "top_ups": [],
    }


def _calibration_queue(run_id, sample_id, seed) -> dict:
    qpath = queue_path("calibration")
    if qpath.exists():
        print(f"reusing queue {qpath}")
        return {"queue": load_queue(qpath), "path": qpath, "reused": True}
    frame = labeling_frame(sample_id, run_id)
    queue = build_queue(
        frame,
        None,
        seed,
        _other_queue_ids(qpath),
        DEFAULT_BANDS,
        DEFAULT_BAND_SIZES,
    )
    queue.update(
        {
            "label_set": "calibration",
            **_queue_meta(run_id, sample_id, "firsthand_problem"),
            "domain_ids": domain_subset(queue["ids"], seed),
        }
    )
    save_queue(queue, qpath)
    return {"queue": queue, "path": qpath, "reused": False}


def _audit_queue(run_id, sample_id, seed) -> dict | None:
    """Audit queue over comments that got facet answers; None when the facet
    stage never ran. `candidates` records the post-exclusion pool so gold
    probabilities stay frozen at draw time."""
    sel_path = paths.run_dir(run_id) / "facet_selection.parquet"
    if not sel_path.exists():
        print(f"no facet_selection.parquet for {run_id}; skipping audit queue")
        return None
    selection = {
        int(r["comment_id"]): r for r in pq.read_table(sel_path).to_pylist()
    }
    qpath = queue_path("audit")
    if qpath.exists():
        print(f"reusing queue {qpath}")
        queue = load_queue(qpath)
        return {
            "queue": queue,
            "path": qpath,
            "reused": True,
            "selection": selection,
        }
    answered = _faceted(run_id)
    candidates = sorted(c for c in selection if c in answered)
    exclude = _other_queue_ids(qpath)
    n_pool = sum(1 for c in candidates if c not in exclude)
    if n_pool:
        queue = build_queue(
            pa.table({"comment_id": pa.array(candidates, type=pa.int64())}),
            min(AUDIT_N, n_pool),
            seed,
            exclude,
        )
    else:
        queue = {"ids": [], "repeats": [], "bands": {}, "rates": {}, "seed": seed}
    queue.update(
        {
            "label_set": "audit",
            **_queue_meta(run_id, sample_id, "facets"),
            "domain_ids": [],
            "candidates": n_pool,
        }
    )
    save_queue(queue, qpath)
    return {
        "queue": queue,
        "path": qpath,
        "reused": False,
        "selection": selection,
    }


def _gold_rows(calibration: dict, audit: dict | None) -> list[dict]:
    """One GOLD_DRAWS row per queue id, in queue order."""
    rows: list[dict] = []
    cqueue = calibration["queue"]
    seed_of = {
        int(cid): int(up["seed"])
        for up in cqueue.get("top_ups") or []
        for cid in up["ids"]
    }
    for band, info in cqueue["bands"].items():
        rate = float(cqueue["rates"][band])
        for cid in info["ids"]:
            rows.append(
                {
                    "label_set": "calibration",
                    "comment_id": int(cid),
                    "draw_stratum": band,
                    "selection_prob": rate,
                    "seed": seed_of.get(int(cid), int(cqueue["seed"])),
                    "purpose": "calibration",
                }
            )
    if audit is None:
        return rows
    aqueue = audit["queue"]
    selection = audit["selection"]
    n_audit = len(aqueue["ids"])
    n_pool = int(aqueue["candidates"])
    for cid in aqueue["ids"]:
        picked = selection[int(cid)]
        rows.append(
            {
                "label_set": "audit",
                "comment_id": int(cid),
                "draw_stratum": "faceted:" + picked["rule"],
                "selection_prob": float(
                    picked["selection_prob"] * (n_audit / n_pool)
                ),
                "seed": int(aqueue["seed"]),
                "purpose": "audit",
            }
        )
    return rows


def _write_gold(rows: list[dict], writing: set[str]) -> tuple[Path, int, int]:
    """Drop existing rows of the label sets being written, keep all others,
    append ours. Returns (path, rows written, total rows)."""
    path = paths.LABELS / GOLD_FILE
    new = pa.Table.from_pylist(rows, schema=contracts.GOLD_DRAWS)
    if path.exists():
        existing = pq.read_table(path)
        keep = existing.filter(
            pc.invert(
                pc.is_in(
                    existing.column("label_set"),
                    value_set=pa.array(sorted(writing)),
                )
            )
        )
        new = pa.concat_tables([keep, new])
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(new, path)
    return path, len(rows), new.num_rows


def build_calibration(run_id, sample_id, seed=1) -> dict:
    """Build (or reuse) the calibration and audit queues for a pilot run and
    refresh their GOLD_DRAWS rows."""
    calibration = _calibration_queue(run_id, sample_id, seed)
    audit = _audit_queue(run_id, sample_id, seed)
    writing = {"calibration"} | ({"audit"} if audit else set())
    rows = _gold_rows(calibration, audit)
    gpath, written, total = _write_gold(rows, writing)
    return {
        "calibration": {
            "path": str(calibration["path"]),
            "ids": len(calibration["queue"]["ids"]),
            "reused": calibration["reused"],
        },
        "audit": (
            {
                "path": str(audit["path"]),
                "ids": len(audit["queue"]["ids"]),
                "reused": audit["reused"],
            }
            if audit
            else None
        ),
        "gold_rows": {
            "path": str(gpath),
            "written": written,
            "total": total,
        },
    }

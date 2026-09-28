"""Snapshot build passes 1 and 2: shard parts, then numpy root resolution.

Pass 1 runs one worker per shard (ProcessPoolExecutor at scale, inline when a
single worker suffices). Each worker normalizes text and detects language for
in-window ok comments, writes `_parts/<shard>.parquet`, and returns the tally
the manifest reconciles against the shard metas.

Pass 2 loads id/parent/type from the parts plus context.jsonl, resolves roots
with `threads.resolve_roots_np`, optionally fetches still-missing ancestors,
and writes `_parts/roots.parquet` plus a context part for pass 3.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas.sources import shards as sh
from atlas.sources.context import load_context
from atlas.sources.htmltext import html_to_text, split_sentences
from atlas.sources.lang import detect_many
from atlas.sources.threads import (
    KIND_COMMENT,
    KIND_OTHER,
    KIND_ROOT,
    ROOT_KINDS,
    kind_code,
    resolve_roots_np,
)

PART_FIELDS = (
    ("id", pa.int64()),
    ("type", pa.string()),
    ("time", pa.int64()),
    ("parent", pa.int64()),
    ("state", pa.string()),
    ("title", pa.string()),
    ("url", pa.string()),
    ("score", pa.int32()),
    ("descendants", pa.int32()),
    ("author", pa.string()),
    ("fetched_at", pa.string()),
    ("text_norm", pa.string()),
    ("sentences", pa.list_(pa.string())),
    ("text_sha256", pa.string()),
    ("word_count", pa.int32()),
    ("lang", pa.string()),
)
PART_SCHEMA = pa.schema(PART_FIELDS)

ROOTS_SCHEMA = pa.schema(
    [
        ("id", pa.int64()),
        ("story_id", pa.int64()),
        ("depth", pa.int64()),
    ]
)

_TALLY_KEYS = (
    "n_records",
    "null",
    "failed",
    "comments",
    "stories",
    "other_types",
    "deleted_without_type",
)


def _empty_tally() -> dict:
    return dict.fromkeys(_TALLY_KEYS, 0)


def _record_row(rec: dict, ws: int, we: int) -> dict | None:
    """One part row for a record with an item; language left for batch fill."""
    item = rec["item"]
    text_norm = html_to_text(item.get("text"))
    return {
        "id": item.get("id", rec["id"]),
        "type": item.get("type"),
        "time": item.get("time"),
        "parent": item.get("parent"),
        "state": rec["state"],
        "title": item.get("title"),
        "url": item.get("url"),
        "score": item.get("score"),
        "descendants": item.get("descendants"),
        "author": item.get("by"),
        "fetched_at": rec.get("ended_at"),
        "text_norm": text_norm,
        "sentences": split_sentences(text_norm),
        "text_sha256": hashlib.sha256(text_norm.encode("utf-8")).hexdigest(),
        "word_count": len(text_norm.split()),
        "lang": "und",
        "_lang_text": item.get("text"),  # dropped before the row is written
    }


def _fill_lang(rows: list[dict], ws: int, we: int) -> None:
    """Detect language only for in-window ok comments with non-empty text."""
    idx = [
        i
        for i, r in enumerate(rows)
        if r["type"] == "comment"
        and r["state"] == "ok"
        and r["time"] is not None
        and ws <= r["time"] < we
        and r["text_norm"] != ""
    ]
    if not idx:
        return
    langs = detect_many(
        [html_to_text(rows[i]["_lang_text"], drop_pre=True) for i in idx]
    )
    for i, lang in zip(idx, langs):
        rows[i]["lang"] = lang


def _rows_table(rows: list[dict]) -> pa.Table:
    cols = {name: [r[name] for r in rows] for name in PART_SCHEMA.names}
    return pa.table(cols, schema=PART_SCHEMA)


def shard_part(job: tuple) -> dict:
    """Worker: (shard_path, part_path, ws, we) -> tally dict. Picklable."""
    shard_path, part_path, ws, we = job
    tally = _empty_tally()
    rows: list[dict] = []
    for rec in sh.read_lines(Path(shard_path)):
        tally["n_records"] += 1
        item = rec.get("item")
        if item is None:
            tally["failed" if rec.get("state") == "failed" else "null"] += 1
            continue
        t = item.get("type")
        if t is None:
            tally["deleted_without_type"] += 1
        elif t == "comment":
            tally["comments"] += 1
        elif t in ("story", "poll", "job"):
            tally["stories"] += 1
        else:
            tally["other_types"] += 1
        rows.append(_record_row(rec, ws, we))
    _fill_lang(rows, ws, we)
    for r in rows:
        r.pop("_lang_text")
    part_path = Path(part_path)
    part_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(_rows_table(rows), part_path, compression="zstd")
    tally["part"] = str(part_path)
    return tally


def run_pass1(
    shard_dir: Path, specs: list, parts_dir: Path, ws: int, we: int, workers: int | None
) -> tuple[list[Path], dict]:
    """Write one part per shard; return (part paths, summed tally)."""
    parts_dir.mkdir(parents=True, exist_ok=True)
    jobs = [
        (sh.paths(shard_dir, s)[0], parts_dir / f"{s.name}.parquet", ws, we)
        for s in specs
    ]
    n_workers = workers or min(6, os.cpu_count() or 1, len(jobs))
    if n_workers <= 1 or len(jobs) <= 1:
        tallies = [shard_part(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            tallies = list(pool.map(shard_part, jobs))
    total = _empty_tally()
    for t in tallies:
        for k in _TALLY_KEYS:
            total[k] += t[k]
    return [Path(t["part"]) for t in tallies], total


def context_rows(context_dir: Path, ws: int, we: int) -> list[dict]:
    """Context records with an item, normalized like part rows (lang 'und')."""
    rows = []
    for rec in load_context(context_dir / "context.jsonl").values():
        if rec.get("item") is None:
            continue
        rows.append(_record_row(rec, ws, we))
    for r in rows:
        r.pop("_lang_text")
    return rows


def _id_frames(part_paths: list[Path], ctx_rows: list[dict]):
    """(ids, parent, kind) sorted-unique arrays; scan ids win over context."""
    ids_c: list[np.ndarray] = []
    parent_c: list[np.ndarray] = []
    kind_c: list[np.ndarray] = []
    for p in part_paths:
        t = pq.read_table(p, columns=["id", "parent", "type"])
        ids_c.append(np.asarray(t.column("id").to_numpy(), dtype=np.int64))
        parent_c.append(
            np.asarray(
                pc.fill_null(t.column("parent"), -1).to_numpy(), dtype=np.int64
            )
        )
        types = np.asarray(t.column("type").to_numpy(), dtype=object)
        kind_c.append(
            np.select(
                [types == "comment", np.isin(types, list(ROOT_KINDS))],
                [KIND_COMMENT, KIND_ROOT],
                KIND_OTHER,
            ).astype(np.int8)
        )
    scan_ids = np.concatenate(ids_c) if ids_c else np.empty(0, dtype=np.int64)
    if ctx_rows:
        ci = np.fromiter(
            (r["id"] for r in ctx_rows), dtype=np.int64, count=len(ctx_rows)
        )
        keep = ~np.isin(ci, scan_ids)
        if keep.any():
            kept = [r for r, k in zip(ctx_rows, keep.tolist()) if k]
            ids_c.append(ci[keep])
            parent_c.append(
                np.fromiter(
                    (-1 if r["parent"] is None else r["parent"] for r in kept),
                    dtype=np.int64,
                    count=len(kept),
                )
            )
            kind_c.append(
                np.fromiter(
                    (kind_code(r["type"]) for r in kept),
                    dtype=np.int8,
                    count=len(kept),
                )
            )
    if not ids_c:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty, np.empty(0, dtype=np.int8)
    arr_ids = np.concatenate(ids_c)
    arr_parent = np.concatenate(parent_c)
    arr_kind = np.concatenate(kind_c)
    uniq, first = np.unique(arr_ids, return_index=True)
    return uniq, arr_parent[first], arr_kind[first]


def run_pass2(
    part_paths: list[Path],
    ctx_rows: list[dict],
    roots_path: Path,
) -> tuple[np.ndarray, int]:
    """Resolve roots over scan+context ids; write roots.parquet for comments.

    Returns (missing, unresolved): the sorted unique absent parent ids and the
    number of comment rows with no resolved root.
    """
    ids, parent, kind = _id_frames(part_paths, ctx_rows)
    root_id, depth, missing = resolve_roots_np(ids, parent, kind)
    is_comment = kind == KIND_COMMENT
    story_ids = [
        int(v) if v >= 0 else None for v in root_id[is_comment].tolist()
    ]
    depths = [int(v) if v >= 0 else None for v in depth[is_comment].tolist()]
    pq.write_table(
        pa.table(
            {
                "id": pa.array(ids[is_comment].tolist(), type=pa.int64()),
                "story_id": pa.array(story_ids, type=pa.int64()),
                "depth": pa.array(depths, type=pa.int64()),
            },
            schema=ROOTS_SCHEMA,
        ),
        roots_path,
        compression="zstd",
    )
    return missing, int((is_comment & (root_id < 0)).sum())


def write_context_part(ctx_rows: list[dict], path: Path) -> Path:
    pq.write_table(_rows_table(ctx_rows), path, compression="zstd")
    return path

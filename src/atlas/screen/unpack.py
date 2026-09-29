"""Per-comment screen table (L17 17.4): unpack packed answers onto the sample.

Only answers whose (packed_id, part) pair is listed in done.jsonl count, so an
orphan part from a crash between write_part and append_done is ignored and a
legit crash never double-counts. Every sampled comment must map to exactly one
non-null firsthand noul.
"""

from __future__ import annotations

import json
import os
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.pilot import packed

SCREEN_BY_COMMENT = pa.schema(
    [
        ("comment_id", pa.int64()),
        ("story_id", pa.int64()),
        ("stratum", pa.string()),
        ("weight", pa.float64()),
        ("half", pa.string()),
        ("firsthand_p", pa.float64()),
        ("packed_id", pa.int64()),
        ("slot", pa.string()),
        ("model_returned", pa.string()),
        ("request_id", pa.string()),
    ]
)

_SLIM_ANSWERS = pa.schema(
    [
        ("comment_id", pa.int64()),
        ("question_id", pa.string()),
        ("noul", pa.float64()),
    ]
)


def _done_pairs(run_dir, question_set: str) -> set[tuple[int, int]]:
    """(packed_id, part) rows from done.jsonl whose part file still exists."""
    pairs = set()
    path = run_dir / "done.jsonl"
    if not path.exists():
        return pairs
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("question_set") != question_set:
            continue
        if (run_dir / "answers" / f"part-{row['part']}.parquet").exists():
            pairs.add((row["comment_id"], row["part"]))
    return pairs


def _authoritative_answers(run_dir, question_set: str, pairs):
    """Slim answer rows plus per-packed-call (model_returned, request_id)."""
    rows = []
    call_info: dict[int, tuple[str | None, str | None]] = {}
    for part in sorted({p for _, p in pairs}):
        table = pq.read_table(
            run_dir / "answers" / f"part-{part}.parquet",
            columns=[
                "comment_id",
                "question_set",
                "question_id",
                "noul",
                "model_returned",
                "request_id",
            ],
        )
        for r in table.to_pylist():
            if (r["comment_id"], part) not in pairs:
                continue
            if r["question_set"] != question_set:
                continue
            rows.append(
                {
                    "comment_id": r["comment_id"],
                    "question_id": r["question_id"],
                    "noul": r["noul"],
                }
            )
            call_info[r["comment_id"]] = (
                r["model_returned"],
                r["request_id"],
            )
    return pa.Table.from_pylist(rows, schema=_SLIM_ANSWERS), call_info


def _problems(label: str, ids) -> str:
    examples = sorted(ids)[:5]
    return f"{label}: {len(ids)} comment(s), e.g. {examples}"


def build_screen_table(run_id: str) -> pa.Table:
    """Join unpacked packed answers onto the sample; write the by-comment table."""
    run_dir = paths.run_dir(run_id)
    params_path = run_dir / "screen.json"
    if not params_path.exists():
        raise SystemExit(f"{params_path} missing; run the screen first")
    params = json.loads(params_path.read_text(encoding="utf-8"))
    question_set = params["question_set"]

    pairs = _done_pairs(run_dir, question_set)
    slim, call_info = _authoritative_answers(run_dir, question_set, pairs)
    packed_map = pq.read_table(run_dir / "packed_map.parquet")
    map_rows = packed_map.to_pylist()

    map_counts = Counter(r["comment_id"] for r in map_rows)
    dup_mapped = [c for c, n in map_counts.items() if n > 1]
    if dup_mapped:
        raise ValueError(_problems("duplicate packed-map rows", dup_mapped))
    slot_of = {r["comment_id"]: (r["packed_id"], r["slot"]) for r in map_rows}

    unpacked = packed.unpack_answers(slim, packed_map)
    answered = Counter(
        r["comment_id"]
        for r in unpacked.to_pylist()
        if r["question_id"] == "firsthand_problem"
    )
    dup_answered = [c for c, n in answered.items() if n > 1]
    if dup_answered:
        raise ValueError(_problems("duplicate answers", dup_answered))
    firsthand = {
        r["comment_id"]: r["noul"]
        for r in unpacked.to_pylist()
        if r["question_id"] == "firsthand_problem"
    }

    sample = pq.read_table(paths.sample_path(params["sample_id"]))
    sample_rows = {r["comment_id"]: r for r in sample.to_pylist()}

    missing = [
        c
        for c in sample_rows
        if c not in firsthand or firsthand[c] is None
    ]
    if missing:
        raise ValueError(_problems("missing answers", missing))
    unexpected = [c for c in firsthand if c not in sample_rows]
    if unexpected:
        raise ValueError(_problems("answers for comments not in sample", unexpected))

    rows = []
    for cid in sorted(sample_rows):
        s = sample_rows[cid]
        packed_id, slot = slot_of[cid]
        model_returned, request_id = call_info.get(packed_id, (None, None))
        story_id = s["story_id"]
        rows.append(
            {
                "comment_id": cid,
                "story_id": story_id,
                "stratum": s["stratum"],
                "weight": s["weight"],
                "half": (
                    contracts.half_of(story_id) if story_id is not None else None
                ),
                "firsthand_p": float(firsthand[cid]),
                "packed_id": packed_id,
                "slot": slot,
                "model_returned": model_returned,
                "request_id": request_id,
            }
        )
    table = pa.Table.from_pylist(rows, schema=SCREEN_BY_COMMENT)
    out = run_dir / "screen_by_comment.parquet"
    tmp = out.with_name(out.name + ".tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, out)
    return table

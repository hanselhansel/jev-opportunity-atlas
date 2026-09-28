"""Unsolved-replies lane (L14): read direct replies to problem comments.

A reply is a snapshot comment whose `parent_id` is the problem comment, so no
network is needed. `reply_pairs` splits replies into other-people replies
(`pairs`) and the problem author's own follow-ups (`author_followups`), each
capped per problem. `reply_items`/`followup_items` build runner items with
per-item `state` and `questions` (the L11 item extension), `mapping_table`
records reply -> problem for joining answers back, and `unsolved_by_problem`
summarizes the answers into one row per problem for L13 `card_metrics`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

TEXT_CAP = 1200


@dataclass
class ReplyPairs:
    pairs: list[dict]
    author_followups: list[dict]


def reply_pairs(snapshot_dir, problem_ids, max_replies=5) -> ReplyPairs:
    """Direct replies to `problem_ids` from the snapshot's comments.parquet.

    Each pair dict is {"problem_id", "reply_id", "time", "text"}, ordered by
    (problem_id, time, reply_id). Only `state = 'ok'` replies with non-blank
    `text_norm` count; `eligible`/`in_window` are ignored on purpose. Replies
    by the problem's own author (both authors non-null and equal) land in
    `author_followups`; each list is capped separately at the first
    `max_replies` by (time, id). Problem ids absent from the snapshot produce
    nothing.
    """
    ids = sorted({int(i) for i in problem_ids})
    if not ids:
        return ReplyPairs(pairs=[], author_followups=[])
    parquet = Path(snapshot_dir) / "comments.parquet"
    if not parquet.exists():
        raise FileNotFoundError(parquet)

    import duckdb

    problems = pa.table({"id": pa.array(ids, type=pa.int64())})
    con = duckdb.connect()
    try:
        con.register("problems", problems)
        rows = con.execute(
            """
            select r.parent_id as problem_id, r.id as reply_id, r.time as time,
                   r.text_norm as text,
                   (p.author is not null and r.author is not null
                    and r.author = p.author) as is_followup
            from read_parquet(?) r
            join problems pr on pr.id = r.parent_id
            join read_parquet(?) p on p.id = r.parent_id
            where r.state = 'ok'
              and r.text_norm is not null
              and regexp_matches(r.text_norm, '\\S')
            qualify row_number() over (
                partition by r.parent_id,
                             (p.author is not null and r.author is not null
                              and r.author = p.author)
                order by r.time, r.id
            ) <= ?
            order by problem_id, time, reply_id
            """,
            [str(parquet), str(parquet), int(max_replies)],
        ).fetchall()
    finally:
        con.close()

    pairs, followups = [], []
    for problem_id, reply_id, time, text, is_followup in rows:
        item = {
            "problem_id": problem_id,
            "reply_id": reply_id,
            "time": time,
            "text": text,
        }
        (followups if is_followup else pairs).append(item)
    return ReplyPairs(pairs=pairs, author_followups=followups)

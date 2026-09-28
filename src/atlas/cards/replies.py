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

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas.inference.questions import QuestionSet, canonical_json

TEXT_CAP = 1200

# Question format mirrors configs/questions/screen.v0.json; noul criteria keys
# are "true"/"false".
REPLY_QUESTIONS = {
    "names_solution": {
        "type": "noul",
        "instructions": "Does `reply` name an existing tool, product, or "
        "approach that would solve `problem`?",
        "criteria": {
            "true": "The reply names a specific existing tool, product, "
            "feature, or approach that addresses the problem.",
            "false": "The reply names no solution: it sympathizes, argues, "
            "asks a question, or names something that does not address the "
            "problem.",
        },
    },
    "solution_kind": {
        "type": "choice",
        "instructions": "What kind of solution does `reply` name for "
        "`problem`?",
        "criteria": {
            "commercial_product": "A paid or commercial product or service.",
            "open_source_tool": "A free or open-source tool or library.",
            "built_in_feature": "A feature already built into the product or "
            "platform the author uses.",
            "process_or_workaround": "A process, practice, or manual "
            "workaround rather than a tool.",
            "none": "No solution is named.",
        },
    },
}

FOLLOWUP_QUESTIONS = {
    "author_says_solved": {
        "type": "choice",
        "instructions": "Does `followup`, written by the author of `problem`, "
        "say the problem is solved?",
        "criteria": {
            "solved": "The author says the problem is solved or a suggested "
            "solution works for them.",
            "still_unsolved": "The author says the problem remains or rejects "
            "the suggested solutions.",
            "unclear": "The follow-up does not say either way.",
        },
    },
}

# reply -> problem join table, written next to the answers so each answer row
# can be traced back to the problem comment it informs.
MAPPING = pa.schema(
    [
        ("reply_id", pa.int64()),
        ("problem_id", pa.int64()),
        ("kind", pa.string()),
        ("time", pa.int64()),
    ]
)


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


def _item(pair, kind, text_field, questions, pain_sentences) -> dict:
    """Runner item (L11 shape): comment_id plus per-item state/questions; the
    runner ignores the extra metadata keys."""
    return {
        "comment_id": pair["reply_id"],
        "problem_id": pair["problem_id"],
        "kind": kind,
        "time": pair["time"],
        "state": {
            "problem": pain_sentences[pair["problem_id"]],
            text_field: pair["text"][:TEXT_CAP],
        },
        "questions": copy.deepcopy(questions),
    }


def reply_items(pairs, pain_sentences) -> list[dict]:
    """One runner item per non-author reply; `pain_sentences` maps problem id
    to the card's problem statement (missing ids raise KeyError)."""
    return [
        _item(p, "reply", "reply", REPLY_QUESTIONS, pain_sentences)
        for p in pairs
    ]


def followup_items(author_followups, pain_sentences) -> list[dict]:
    """One runner item per author follow-up; same contract as `reply_items`."""
    return [
        _item(p, "followup", "followup", FOLLOWUP_QUESTIONS, pain_sentences)
        for p in author_followups
    ]


def _question_set(name, state_fields, questions) -> QuestionSet:
    return QuestionSet(
        name=name,
        version=1,
        label=f"{name}@1",
        state_fields=list(state_fields),
        questions=copy.deepcopy(questions),
        sha256=hashlib.sha256(
            canonical_json(questions).encode("utf-8")
        ).hexdigest(),
    )


def reply_question_set() -> QuestionSet:
    return _question_set("replies", ["problem", "reply"], REPLY_QUESTIONS)


def followup_question_set() -> QuestionSet:
    return _question_set(
        "reply-followups", ["problem", "followup"], FOLLOWUP_QUESTIONS
    )


def mapping_table(items) -> pa.Table:
    """reply_id -> problem_id join table for the answers these items produce."""
    return pa.Table.from_pylist(
        [
            {
                "reply_id": it["comment_id"],
                "problem_id": it["problem_id"],
                "kind": it["kind"],
                "time": it["time"],
            }
            for it in items
        ],
        schema=MAPPING,
    )


def write_mapping(items, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(mapping_table(items), path)
    return path

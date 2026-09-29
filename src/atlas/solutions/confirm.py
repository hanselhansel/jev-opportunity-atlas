"""S5 confirm: one Jev yes/no per (reply, tool) mention hit.

A mention in a problem comment is a complaint and costs nothing. A mention
in a reply or author follow-up is a fix candidate: Jev answers
`recommends` for each (reply, tool) pair. Runner items carry a synthetic
`comment_id` (`hit_id`, a sha256 of "comment_id|tool") because the runner's
done set keys on comment_id and one reply can name several tools; the real
reply id stays on the item as `reply_id` and in mentions.parquet.
"""

from __future__ import annotations

import copy
import hashlib

from atlas.cards.replies import TEXT_CAP
from atlas.inference.questions import QuestionSet, canonical_json

QUESTIONS = {
    "recommends": {
        "type": "noul",
        "instructions": "Does `reply` recommend `tool` as a fix for "
        "`problem`?",
        "criteria": {
            "true": "The reply recommends or points to `tool` as a way to "
            "fix, work around, or avoid `problem`.",
            "false": "The reply does not recommend `tool` for `problem`: "
            "it only mentions it in passing, compares against it, or names "
            "it as part of the problem.",
        },
    },
}

QUESTION_SET_LABEL = "solutions@1"
RECOMMENDS_MIN = 0.5


def question_set() -> QuestionSet:
    return QuestionSet(
        name="solutions",
        version=1,
        label=QUESTION_SET_LABEL,
        state_fields=["problem", "reply", "tool"],
        questions=copy.deepcopy(QUESTIONS),
        sha256=hashlib.sha256(
            canonical_json(QUESTIONS).encode("utf-8")
        ).hexdigest(),
    )


def hit_id(comment_id: int, tool: str) -> int:
    """Stable positive int64 surrogate key for one (comment, tool) pair."""
    digest = hashlib.sha256(f"{comment_id}|{tool}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & (2**63 - 1)


def confirm_items(hits) -> list[dict]:
    """One runner item per reply-kind mention hit.

    Each hit dict carries comment_id (the reply), problem_id, tool, text,
    and pain (the problem's pain sentence). The item's comment_id is the
    surrogate hit_id so multi-tool replies resume correctly; `reply_id`,
    `problem_id`, and `tool` ride along as metadata the runner ignores.
    """
    items = []
    for h in sorted(hits, key=lambda h: (h["comment_id"], h["tool"])):
        items.append(
            {
                "comment_id": hit_id(h["comment_id"], h["tool"]),
                "reply_id": h["comment_id"],
                "problem_id": h["problem_id"],
                "tool": h["tool"],
                "state": {
                    "problem": h["pain"],
                    "reply": (h["text"] or "")[:TEXT_CAP],
                    "tool": h["tool"],
                },
                "questions": copy.deepcopy(QUESTIONS),
            }
        )
    return items


def confirmed_ids(answers) -> set[int]:
    """hit_ids whose `recommends` noul reached the confirm threshold."""
    out = set()
    for row in answers.to_pylist():
        if (
            row["question_set"] == QUESTION_SET_LABEL
            and row["question_id"] == "recommends"
            and row["noul"] is not None
            and row["noul"] >= RECOMMENDS_MIN
        ):
            out.add(int(row["comment_id"]))
    return out

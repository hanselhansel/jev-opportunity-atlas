"""Membership verification: one noul question per assigned comment,
"Does `problem` describe this need: `card`?" Fills verified_p on ASSIGNMENTS
rows; everything else is copied through unchanged."""

from __future__ import annotations

from atlas.cards.engine.assign import AssignResult, engine_qs, read_answers
from atlas.inference.runner import run_batch

VERIFY_INSTRUCTIONS = "Does `problem` describe this need: `card`?"
VERIFY_CRITERIA = {
    "true": "Yes, `problem` is an instance of the need in `card`.",
    "false": "No, it is a different need.",
}
VERIFY_TEMPLATE = {"member": {"type": "noul", "instructions": VERIFY_INSTRUCTIONS}}


def _rows_of(assignments) -> list[dict]:
    if isinstance(assignments, AssignResult):
        return assignments.rows
    return list(assignments)


async def verify(ctx, assignments, pain_sentences: dict, cs) -> list[dict]:
    rows = _rows_of(assignments)
    qs = engine_qs("verify", cs, VERIFY_TEMPLATE)
    items = []
    for row in rows:
        card_id = row.get("card_id")
        if card_id in (None, "none"):
            continue
        pain = pain_sentences.get(row["comment_id"])
        if pain is None:
            continue
        card = cs.all_cards[cs.resolve(card_id)]
        items.append(
            {
                "comment_id": row["comment_id"],
                "state": {"problem": pain, "card": card.statement},
                "questions": {
                    "member": {
                        "type": "noul",
                        "instructions": VERIFY_INSTRUCTIONS,
                        "criteria": dict(VERIFY_CRITERIA),
                    }
                },
            }
        )
    if items:
        await run_batch(ctx, items, qs)
    answers = read_answers(ctx.run_dir, qs.label)
    out = []
    for row in rows:
        new = dict(row)
        answer = answers.get(row["comment_id"], {}).get("member")
        if answer is not None and answer.get("noul") is not None:
            new["verified_p"] = answer["noul"]
        out.append(new)
    return out

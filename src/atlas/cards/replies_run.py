"""`cards replies` (L23): the unsolved-replies check over an assign run.

Problems are the run's assigned comments with a real card at card_p >= 0.5,
optionally limited to the top `--top-cards` cards by qualifying count. Reply
pairs come from the snapshot via atlas.cards.replies.reply_pairs; items are
built by reply_items/followup_items with the pain sentences the assign run
wrote to pain.parquet. Everything lands in `<run>/replies/` so the assign
run's own answers stay untouched; reruns resume through the runner's done
set, so no paid call repeats.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts
from atlas.cards import replies
from atlas.inference.questions import canonical_json
from atlas.inference.runner import raise_for_stopped, run_batch

MODEL = "jev-1.13.0"
MIN_CARD_P = 0.5


def selected_problems(
    rows, top_cards=None, min_card_p=MIN_CARD_P, resolve=None
) -> list[int]:
    """Sorted comment ids assigned a real card at card_p >= min_card_p.

    With `top_cards`, first keep the N card ids with the most qualifying
    assignments (ties break on card id), then keep only their comments.
    `resolve` maps merged card ids to their final card before the top-cards
    count, so a merged card's problems rank with the card they merged into.
    """
    qual = []
    for r in rows:
        card = r.get("card_id")
        if card in (None, "none") or (r.get("card_p") or 0.0) < min_card_p:
            continue
        if resolve is not None:
            card = resolve(card)
            if card is None:
                continue
        qual.append((int(r["comment_id"]), card))
    if top_cards is not None:
        counts = Counter(card for _cid, card in qual)
        keep = {
            cid
            for cid, _n in sorted(
                counts.items(), key=lambda kv: (-kv[1], kv[0])
            )[:top_cards]
        }
        qual = [pair for pair in qual if pair[1] in keep]
    return sorted({cid for cid, _card in qual})


def collect_items(
    snapshot_dir, problem_ids, pain_sentences, max_replies=5
) -> list[dict]:
    """Runner items for every reply and author follow-up to `problem_ids`;
    replies to problems without a pain sentence are skipped."""
    pairs = replies.reply_pairs(
        snapshot_dir, problem_ids, max_replies=max_replies
    )
    reply_rows = [p for p in pairs.pairs if p["problem_id"] in pain_sentences]
    follow_rows = [
        f for f in pairs.author_followups if f["problem_id"] in pain_sentences
    ]
    return replies.reply_items(
        reply_rows, pain_sentences
    ) + replies.followup_items(follow_rows, pain_sentences)


def item_tokens(item: dict) -> int:
    """Estimated input tokens for one reply item (same bytes/3.2 estimate the
    other card commands use)."""
    body = {
        "state": item["state"],
        "model": MODEL,
        "questions": item["questions"],
    }
    return math.ceil(len(canonical_json(body).encode("utf-8")) / 3.2)


async def run(ctx, items) -> dict:
    """Two run_batch passes over ctx.run_dir: replies under replies@1, then
    author follow-ups under reply-followups@1."""
    out = {"replies": None, "followups": None}
    reply_items = [it for it in items if it["kind"] == "reply"]
    follow_items = [it for it in items if it["kind"] == "followup"]
    if reply_items:
        out["replies"] = await run_batch(
            ctx, reply_items, replies.reply_question_set()
        )
        raise_for_stopped(
            ctx, out["replies"], len(reply_items) + len(follow_items)
        )
    if follow_items:
        out["followups"] = await run_batch(
            ctx, follow_items, replies.followup_question_set()
        )
        prior = 0
        if out["replies"]:
            prior = (
                out["replies"]["completed"]
                + out["replies"]["skipped_completed"]
            )
        raise_for_stopped(
            ctx, out["followups"], len(follow_items), prior=prior
        )
    return out


def answers_table(run_dir) -> pa.Table:
    """Concatenated ANSWERS from `<run_dir>/answers/part-*.parquet` (empty
    contract table when nothing has been written)."""
    answers_dir = Path(run_dir) / "answers"
    parts = sorted(
        answers_dir.glob("part-*.parquet"),
        key=lambda p: int(p.stem.rsplit("-", 1)[1]),
    )
    if not parts:
        return pa.Table.from_pylist([], schema=contracts.ANSWERS)
    return pa.concat_tables([pq.read_table(p) for p in parts])


def write_outputs(run_dir, items, answers) -> dict:
    """Write mapping.parquet and unsolved_by_problem.parquet; returns the
    paths plus row counts for the CLI summary."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    mapping = replies.mapping_table(items)
    mapping_path = run_dir / "mapping.parquet"
    pq.write_table(mapping, mapping_path)
    unsolved = replies.unsolved_by_problem(answers, mapping)
    unsolved_path = run_dir / "unsolved_by_problem.parquet"
    pq.write_table(unsolved, unsolved_path)
    return {
        "answers_dir": str(run_dir / "answers"),
        "mapping": str(mapping_path),
        "unsolved_by_problem": str(unsolved_path),
        "problems_with_answers": unsolved.num_rows,
    }

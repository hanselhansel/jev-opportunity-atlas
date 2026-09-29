"""Merge candidates: within-group pairs plus cross-group pairs backed by
level-2 runner-up evidence, scored by Jev on a 3-level scale. Suggestions only;
the cardset is never modified."""

from __future__ import annotations

import hashlib
import itertools
import json

from atlas.cards.engine.assign import engine_qs, read_answers
from atlas.inference.runner import raise_for_stopped, run_batch

MERGE_LEVELS = [
    "different problems",
    "related but distinct",
    "the same underlying problem",
]
MERGE_INSTRUCTIONS = "How do the needs in `card_a` and `card_b` relate?"
MERGE_TEMPLATE = {"same": {"type": "score", "instructions": MERGE_INSTRUCTIONS}}
DEFAULT_THRESHOLD = 1.6


def pair_id(version: str, a: str, b: str) -> int:
    return int(hashlib.sha256(f"{version}:{a}:{b}".encode()).hexdigest()[:15], 16)


def merge_pairs(
    cs, assignments, cross_group_min_overlap=3, all_pairs=False
) -> list[tuple[str, str]]:
    """Every within-group pair of active cards, plus cross-group pairs whose
    two cards appear together in at least `cross_group_min_overlap` comments'
    card_top2 metadata. With `all_pairs`, every pair of active cards across
    all groups (n*(n-1)/2) regardless of evidence."""
    if all_pairs:
        return list(itertools.combinations(sorted(cs.cards), 2))
    pairs: set[tuple[str, str]] = set()
    for gid in cs.groups:
        ids = sorted(c.card_id for c in cs.cards_in(gid))
        pairs.update(itertools.combinations(ids, 2))
    overlap: dict[tuple[str, str], int] = {}
    for meta in assignments.meta.values():
        seen = set()
        for cid in meta.get("card_top2") or []:
            try:
                cid = cs.resolve(cid)
            except ValueError:
                continue
            if cid in cs.cards:
                seen.add(cid)
        for a, b in itertools.combinations(sorted(seen), 2):
            if cs.cards[a].group_id == cs.cards[b].group_id:
                continue
            key = (a, b)
            overlap[key] = overlap.get(key, 0) + 1
    pairs.update(p for p, n in overlap.items() if n >= cross_group_min_overlap)
    return sorted(pairs)


def merge_item(version: str, a: str, b: str, cs) -> dict:
    return {
        "comment_id": pair_id(version, a, b),
        "state": {
            "card_a": cs.all_cards[a].statement,
            "card_b": cs.all_cards[b].statement,
        },
        "questions": {
            "same": {
                "type": "score",
                "instructions": MERGE_INSTRUCTIONS,
                "criteria": list(MERGE_LEVELS),
            }
        },
    }


async def score_merges(ctx, pairs, cs) -> list[dict]:
    qs = engine_qs("merge", cs, MERGE_TEMPLATE)
    items = [merge_item(cs.version, a, b, cs) for a, b in pairs]
    if items:
        out = await run_batch(ctx, items, qs)
        raise_for_stopped(ctx, out, len(items))
    answers = read_answers(ctx.run_dir, qs.label)
    scored = []
    for a, b in pairs:
        row = answers.get(pair_id(cs.version, a, b), {}).get("same")
        if row is None or row.get("score") is None:
            continue
        probs = (
            json.loads(row["probabilities_json"])
            if row.get("probabilities_json")
            else None
        )
        if probs:
            expected = sum(int(i) * p for i, p in probs.items())
        else:
            expected = row["score"]
        scored.append(
            {
                "card_a": a,
                "card_b": b,
                "score": row["score"],
                "expected": expected,
                "probabilities": probs,
            }
        )
    return scored


def propose_merges(scored, threshold=DEFAULT_THRESHOLD) -> list[dict]:
    """Pairs at or above the expected-score threshold, best first."""
    out = [s for s in scored if s["expected"] >= threshold]
    return sorted(out, key=lambda s: (-s["expected"], s["card_a"], s["card_b"]))

"""Task 11.5: merge pair candidates, merge scoring, proposals."""

import asyncio

from atlas.cards.engine.assign import AssignResult
from atlas.cards.engine.cardset import Card, CardSet, load_cardset
from atlas.cards.engine.merge import (
    MERGE_LEVELS,
    merge_pairs,
    pair_id,
    propose_merges,
    score_merges,
)
from tests.cards.test_engine_support import make_ctx, make_transport


def _cs():
    return load_cardset("example", "t0")


def _three_group_cs():
    cs = _cs()
    groups = dict(cs.groups, g03="Third test group")
    extra_a = Card("c0010", "g03", "Extra card alpha", "approved")
    extra_b = Card("c0011", "g03", "Extra card beta", "approved")
    cards = dict(cs.cards, c0010=extra_a, c0011=extra_b)
    all_cards = dict(cs.all_cards, c0010=extra_a, c0011=extra_b)
    return CardSet(cs.name, cs.version, groups, cards, all_cards, cs.sha256)


def test_within_group_pairs():
    cs = _three_group_cs()
    result = AssignResult()
    pairs = merge_pairs(cs, result)
    assert ("c0001", "c0002") in pairs
    assert ("c0010", "c0011") in pairs
    assert all(cs.cards[a].group_id == cs.cards[b].group_id for a, b in pairs)


def test_cross_group_needs_three_overlaps():
    cs = _three_group_cs()

    def result_with(n):
        return AssignResult(
            meta={i: {"card_top2": ["c0001", "c0010"]} for i in range(n)}
        )

    assert ("c0001", "c0010") not in merge_pairs(cs, result_with(2))
    assert ("c0001", "c0010") in merge_pairs(cs, result_with(3))


def test_cross_group_skips_unknown_ids():
    cs = _cs()
    result = AssignResult(
        meta={i: {"card_top2": ["c0001", "ghost"]} for i in range(5)}
    )
    pairs = merge_pairs(cs, result)
    assert all("ghost" not in p for p in pairs)


def test_pair_id_deterministic_int64():
    a = pair_id("t0", "c0001", "c0002")
    assert a == pair_id("t0", "c0001", "c0002")
    assert 0 <= a < 2**60
    assert a != pair_id("t0", "c0001", "c0003")


def test_score_merges_through_mock(tmp_path):
    cs = _three_group_cs()
    pairs = [("c0001", "c0002"), ("c0001", "c0010")]
    seen = []

    def score(state, qid, n):
        return 2 if state["card_b"] == cs.cards["c0002"].statement else 0

    ctx = make_ctx(tmp_path, make_transport(score=score, seen=seen))
    scored = asyncio.run(score_merges(ctx, pairs, cs))
    assert len(scored) == 2 and len(seen) == 2
    same = next(s for s in scored if s["card_b"] == "c0002")
    assert same["score"] == 2.0 and same["expected"] == 2.0
    assert same["probabilities"] == {"0": 0.0, "1": 0.0, "2": 1.0}
    diff = next(s for s in scored if s["card_b"] == "c0010")
    assert diff["expected"] == 0.0


def test_propose_merges_threshold():
    scored = [
        {"card_a": "a", "card_b": "b", "score": 2.0, "expected": 2.1,
         "probabilities": {}},
        {"card_a": "a", "card_b": "c", "score": 1.0, "expected": 1.6,
         "probabilities": {}},
        {"card_a": "c", "card_b": "d", "score": 0.0, "expected": 1.59,
         "probabilities": {}},
    ]
    out = propose_merges(scored)
    assert [s["expected"] for s in out] == [2.1, 1.6]
    assert len(MERGE_LEVELS) == 3

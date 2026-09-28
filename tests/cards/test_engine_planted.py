"""Task 11.7: planted synthetic needs, decoys, and recovery scoring."""

import asyncio

import pytest

from atlas.cards.engine.assign import assign
from atlas.cards.engine.cardset import CardSetError, load_cardset
from atlas.cards.engine.planted import (
    load_planted,
    planted_items,
    planted_score,
    with_planted,
)
from tests.cards.test_engine_support import make_ctx, make_transport


def test_planted_file_loads_and_shapes():
    planted = load_planted("v1")
    cs = planted.cardset
    assert set(cs.cards) == {"pc01", "pc02", "pc03", "pc04", "pc05"}
    assert all(cs.cards[c].group_id == "gp1" for c in cs.cards)
    assert len(planted.comments) == 50 and len(planted.decoys) == 10
    assert all(c["comment_id"] >= 9_200_000_000 for c in planted.comments)
    assert all(d["comment_id"] >= 9_200_000_000 for d in planted.decoys)
    ids = [c["comment_id"] for c in planted.comments]
    ids += [d["comment_id"] for d in planted.decoys]
    assert len(set(ids)) == 60
    assert len({c["card_id"] for c in planted.comments}) == 5
    assert all(
        sum(1 for c in planted.comments if c["card_id"] == card) == 10
        for card in cs.cards
    )


def _truth_chooser(planted):
    truth = {c["text"]: c["card_id"] for c in planted.comments}

    def chooser(state, qid, options):
        card = truth.get(state["problem"])
        if qid == "group":
            return "gp1" if card else "none"
        return card or "none"

    return chooser


def test_full_recovery_with_correct_chooser(tmp_path):
    planted = load_planted("v1")
    ctx = make_ctx(tmp_path, make_transport(chooser=_truth_chooser(planted)))
    result = asyncio.run(assign(ctx, planted_items(planted), planted.cardset))
    score = planted_score(result.rows, planted)
    assert score["recovery"] == 1.0
    assert score["decoy_false_rate"] == 0.0
    assert score["n_planted"] == 50 and score["n_decoys"] == 10
    assert set(score["per_need"]) == set(planted.cardset.cards)
    assert all(v == 1.0 for v in score["per_need"].values())


def test_wrong_chooser_drops_recovery(tmp_path):
    planted = load_planted("v1")
    ctx = make_ctx(tmp_path, make_transport())  # default: first option
    result = asyncio.run(assign(ctx, planted_items(planted), planted.cardset))
    score = planted_score(result.rows, planted)
    assert score["recovery"] < 1.0
    assert score["decoy_false_rate"] == 1.0  # decoys assigned pc01


def test_missing_rows_count_as_misses():
    planted = load_planted("v1")
    score = planted_score([], planted)
    assert score["recovery"] == 0.0 and score["decoy_false_rate"] == 0.0


def test_with_planted_merges_groups():
    base = load_cardset("example", "t0")
    planted = load_planted("v1")
    merged = with_planted(base, planted)
    assert "gp1" in merged.groups and "g01" in merged.groups
    assert "pc01" in merged.cards and "c0001" in merged.cards
    assert merged.version == "t0+planted-v1"
    assert merged.sha256 != base.sha256
    with pytest.raises(CardSetError):  # applying the same planted set collides
        with_planted(merged, planted)


def test_planted_items_shape():
    planted = load_planted("v1")
    items = planted_items(planted)
    assert len(items) == 60
    assert all(
        set(i) == {"comment_id", "pain_sentence", "sentences"} for i in items
    )

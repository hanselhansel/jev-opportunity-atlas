"""Tasks 11.3 and 11.4: two-level assignment, assignment files, residue sample."""

import asyncio
import json

import pytest

from atlas.cards.engine.assign import (
    CARD_NONE_TEXT,
    GROUP_NONE_TEXT,
    assign,
    assignments_path,
    card_item,
    check_lengths,
    engine_qs,
    group_item,
    load_assignments,
    residue_sample,
    write_assignments,
)
from atlas.cards.engine.cardset import Card, CardSet, CardSetError, load_cardset
from tests.cards.test_engine_support import make_ctx, make_transport


def _cs():
    return load_cardset("example", "t0")


def _rows():
    return [
        {"comment_id": 9_000_000_301, "pain_sentence": "ci keeps failing",
         "sentences": ["ci keeps failing", "it wastes mornings"]},
        {"comment_id": 9_000_000_302, "pain_sentence": "invoices by hand",
         "sentences": ["invoices by hand"]},
        {"comment_id": 9_000_000_303, "pain_sentence": "nothing fits me",
         "sentences": ["nothing fits me"]},
        {"comment_id": 9_000_000_304, "pain_sentence": "weird cardless pain",
         "sentences": ["weird cardless pain"]},
    ]


def test_group_item_shape():
    cs = _cs()
    item = group_item(7, "pain", ["a", "b"], cs)
    assert item["comment_id"] == 7
    assert item["state"] == {"problem": "pain", "sentences": {"s0": "a", "s1": "b"}}
    q = item["questions"]["group"]
    assert q["type"] == "choice"
    assert list(q["criteria"])[:2] == ["g01", "g02"]
    assert q["criteria"]["none"] == GROUP_NONE_TEXT
    assert "comment" not in item


def test_card_item_shape_only_active_cards():
    cs = _cs()
    item = card_item(7, "pain", ["a"], cs, "g02")
    crit = item["questions"]["card"]["criteria"]
    assert list(crit) == ["c0003", "none"]  # draft/merged cards excluded
    assert crit["none"] == CARD_NONE_TEXT


def test_engine_qs_tracks_cardset_and_template():
    cs = _cs()
    t1 = {"group": {"type": "choice", "instructions": "a"}}
    qs1 = engine_qs("assign-g", cs, t1)
    assert qs1.label == "assign-g@t0" and qs1.state_fields == []
    qs2 = engine_qs("assign-g", cs, {"group": {"type": "choice", "instructions": "b"}})
    assert qs1.sha256 != qs2.sha256


def test_check_lengths_raises():
    cs = _cs()
    check_lengths(cs)
    long_label = dict(cs.groups, g01=" ".join(["w"] * 9))
    bad = CardSet(cs.name, cs.version, long_label, cs.cards, cs.all_cards, cs.sha256)
    with pytest.raises(CardSetError):
        check_lengths(bad)
    wordy = Card("cx", "g01", " ".join(["w"] * 21), "approved")
    cards = dict(cs.cards, cx=wordy)
    bad2 = CardSet(cs.name, cs.version, cs.groups, cards,
                   dict(cs.all_cards, cx=wordy), cs.sha256)
    with pytest.raises(CardSetError):
        check_lengths(bad2)


def _chooser(state, qid, options):
    problem = state["problem"]
    if qid == "group":
        if "ci" in problem:
            return "g01"
        if "invoices" in problem:
            return "g02"
        if "cardless" in problem:
            return "g01"
        return "none"
    if qid == "card":
        if "ci" in problem:
            return "c0001"
        if "invoices" in problem:
            return "c0003"
        return "none"
    raise AssertionError(qid)


def test_assign_end_to_end(tmp_path):
    cs = _cs()
    seen = []
    ctx = make_ctx(tmp_path, make_transport(chooser=_chooser, seen=seen))
    result = asyncio.run(assign(ctx, _rows(), cs))
    by_cid = {r["comment_id"]: r for r in result.rows}
    assert by_cid[9_000_000_301]["group_id"] == "g01"
    assert by_cid[9_000_000_301]["card_id"] == "c0001"
    assert by_cid[9_000_000_301]["group_p"] == 1.0
    assert by_cid[9_000_000_303]["group_id"] == "none"
    assert by_cid[9_000_000_303]["card_id"] is None
    assert by_cid[9_000_000_304]["group_id"] == "g01"
    assert by_cid[9_000_000_304]["card_id"] == "none"
    bodies = [json.loads(r.content) for r in seen]
    level2 = [b for b in bodies if "card" in b["questions"]]
    assert len(level2) == 3  # group-none comment never reaches level 2
    assert all(
        b["state"]["problem"] != "nothing fits me" for b in level2
    )


def test_assign_labels_and_meta(tmp_path):
    cs = _cs()
    ctx = make_ctx(tmp_path, make_transport(chooser=_chooser))
    result = asyncio.run(assign(ctx, _rows(), cs))
    labels = {
        json.loads(line)["question_set"]
        for line in (tmp_path / "r1" / "done.jsonl").read_text().splitlines()
    }
    assert labels == {"assign-g@t0", "assign-c@t0"}
    meta = result.meta[9_000_000_301]
    assert meta["card_top2"] == ["c0001", "c0002"]
    assert meta["group_probs"]["g01"] == 1.0 and meta["low_confidence"] is False


def test_low_confidence_flag(tmp_path):
    cs = _cs()
    def confidence(state, qid):
        return 0.3 if qid == "card" else 0.9
    ctx = make_ctx(tmp_path, make_transport(chooser=_chooser, confidence=confidence))
    result = asyncio.run(assign(ctx, _rows()[:1], cs))
    row = result.rows[0]
    assert row["card_id"] == "c0001" and row["card_confidence"] == 0.3
    assert result.meta[row["comment_id"]]["low_confidence"] is True


def test_write_load_roundtrip(tmp_path):
    cs = _cs()
    ctx = make_ctx(tmp_path, make_transport(chooser=_chooser))
    result = asyncio.run(assign(ctx, _rows(), cs))
    write_assignments(ctx.run_dir, result, cs.version)
    loaded = load_assignments(ctx.run_dir, cs.version)
    assert loaded.rows == result.rows
    assert loaded.meta == result.meta
    assert assignments_path(ctx.run_dir, "t0").name == "assignments-t0.parquet"


def _a(cid, group, card):
    return {"comment_id": cid, "group_id": group, "card_id": card}


def test_residue_sample_deterministic_and_stratified():
    rows = (
        [_a(i, "g1", "c1") for i in range(10)]
        + [_a(100 + i, "g1", "none") for i in range(10)]
        + [_a(200 + i, "none", None) for i in range(4)]
        + [_a(300 + i, "g2", "none") for i in range(6)]
    )
    out = residue_sample(rows, k=10, seed=7)
    assert out == residue_sample(rows, k=10, seed=7)
    assert out["n_residue"] == 20 and out["n_total"] == 30
    assert len(out["sample"]) == 10
    assert set(out["sample"]) <= {r["comment_id"] for r in rows
                                  if r["group_id"] == "none"
                                  or r["card_id"] == "none"}
    for g in ("g1", "g2", "none"):
        ids = {r["comment_id"] for r in rows if r["group_id"] == g}
        assert ids & set(out["sample"])  # every non-empty stratum contributes
    assert out["share"] == pytest.approx(20 / 30)
    assert out["share_by_group"]["g1"] == pytest.approx(0.5)
    assert out["share_by_group"]["g2"] == pytest.approx(1.0)
    assert out["share_by_group"]["none"] == pytest.approx(1.0)


def test_residue_sample_k_larger_than_residue():
    rows = [_a(i, "g1", "none") for i in range(3)] + [_a(9, "g1", "c1")]
    out = residue_sample(rows, k=50, seed=1)
    assert sorted(out["sample"]) == [0, 1, 2]
    assert out["n_residue"] == 3


def test_residue_sample_empty():
    out = residue_sample([], k=5, seed=1)
    assert out["sample"] == [] and out["share"] == 0.0

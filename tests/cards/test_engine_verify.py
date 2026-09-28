"""Task 11.6: membership verification fills verified_p via one noul per
assigned comment; unassigned rows are untouched and never sent."""

import asyncio
import json

from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.verify import verify
from tests.cards.test_engine_support import make_ctx, make_transport


def _cs():
    return load_cardset("example", "t0")


def _rows():
    return [
        {"run_id": "r1", "comment_id": 9_000_000_401, "taxonomy_version": "t0",
         "group_id": "g01", "group_p": 1.0, "group_confidence": 0.9,
         "card_id": "c0001", "card_p": 1.0, "card_confidence": 0.9,
         "verified_p": None},
        {"run_id": "r1", "comment_id": 9_000_000_402, "taxonomy_version": "t0",
         "group_id": "g02", "group_p": 1.0, "group_confidence": 0.9,
         "card_id": "c0005", "card_p": 1.0, "card_confidence": 0.9,
         "verified_p": None},  # merged card resolves to c0003's statement
        {"run_id": "r1", "comment_id": 9_000_000_403, "taxonomy_version": "t0",
         "group_id": "none", "group_p": 1.0, "group_confidence": 0.9,
         "card_id": None, "card_p": None, "card_confidence": None,
         "verified_p": None},
        {"run_id": "r1", "comment_id": 9_000_000_404, "taxonomy_version": "t0",
         "group_id": "g01", "group_p": 1.0, "group_confidence": 0.9,
         "card_id": "none", "card_p": 1.0, "card_confidence": 0.9,
         "verified_p": None},
        {"run_id": "r1", "comment_id": 9_000_000_405, "taxonomy_version": "t0",
         "group_id": "g01", "group_p": 1.0, "group_confidence": 0.9,
         "card_id": "c0002", "card_p": 1.0, "card_confidence": 0.9,
         "verified_p": None},  # no pain sentence: not sent
    ]


def test_verify_fills_verified_p(tmp_path):
    cs = _cs()
    seen = []

    def noul(state, qid):
        return {"ci pain": 0.95, "invoice pain": 0.4}[state["problem"]]

    pain = {9_000_000_401: "ci pain", 9_000_000_402: "invoice pain"}
    ctx = make_ctx(tmp_path, make_transport(noul=noul, seen=seen))
    out = asyncio.run(verify(ctx, _rows(), pain, cs))
    by_cid = {r["comment_id"]: r for r in out}
    assert by_cid[9_000_000_401]["verified_p"] == 0.95
    assert by_cid[9_000_000_402]["verified_p"] == 0.4
    assert by_cid[9_000_000_403]["verified_p"] is None
    assert by_cid[9_000_000_404]["verified_p"] is None
    assert by_cid[9_000_000_405]["verified_p"] is None
    assert len(seen) == 2  # only card-assigned rows with a pain sentence
    bodies = [json.loads(r.content) for r in seen]
    by_problem = {b["state"]["problem"]: b for b in bodies}
    merged = by_problem["invoice pain"]
    assert merged["state"]["card"] == cs.all_cards["c0003"].statement
    assert merged["questions"]["member"]["type"] == "noul"


def test_verify_accepts_assign_result(tmp_path):
    from atlas.cards.engine.assign import AssignResult

    cs = _cs()
    ctx = make_ctx(tmp_path, make_transport(noul=lambda s, q: 0.7))
    result = AssignResult(rows=_rows()[:1])
    pain = {9_000_000_401: "ci pain"}
    out = asyncio.run(verify(ctx, result, pain, cs))
    assert out[0]["verified_p"] == 0.7
    assert result.rows[0]["verified_p"] is None  # input untouched

"""Task 11.1: an item may carry its own `state` and `questions`, bypassing
build_state/questions_for. Cache keys, answer rows, and done tracking all key
on the overridden values and the item's comment_id."""

import asyncio
import json

import pyarrow.parquet as pq

from atlas.inference.questions import QuestionSet
from atlas.inference.runner import run_batch
from tests.cards.test_engine_support import make_ctx
from tests.inference.mock_jev import make_transport

NOUL = {"type": "noul", "instructions": "?", "criteria": {"true": "y", "false": "n"}}


def _qs():
    return QuestionSet(
        name="ovr", version=1, label="ovr@1", state_fields=[],
        questions={}, sha256="0" * 64,
    )


def _item(state=None):
    return {
        "comment_id": 9_000_000_101,
        "state": state or {"problem": "I cannot export reports"},
        "questions": {"q": dict(NOUL)},
    }


def _answers(run_dir):
    return pq.read_table(run_dir / "answers").to_pylist()


def test_item_state_and_questions_sent_verbatim(tmp_path):
    item = _item()
    seen = []
    out = asyncio.run(
        run_batch(make_ctx(tmp_path, make_transport([], seen)), [item], _qs())
    )
    assert out["completed"] == 1 and len(seen) == 1
    body = json.loads(seen[0].content)
    assert body["state"] == item["state"]
    assert body["questions"] == item["questions"]
    rows = _answers(tmp_path / "r1")
    assert [r["comment_id"] for r in rows] == [item["comment_id"]]
    assert rows[0]["question_set"] == "ovr@1" and rows[0]["question_id"] == "q"
    assert rows[0]["noul"] == 0.8


def test_done_tracking_skips_overridden_item(tmp_path):
    item = _item()
    asyncio.run(run_batch(make_ctx(tmp_path, make_transport([])), [item], _qs()))
    seen = []
    out = asyncio.run(
        run_batch(make_ctx(tmp_path, make_transport([], seen)), [item], _qs())
    )
    assert out["skipped_completed"] == 1 and seen == []


def test_cache_key_uses_overrides(tmp_path):
    qs = _qs()
    asyncio.run(run_batch(make_ctx(tmp_path, make_transport([])), [_item()], qs))
    other = make_ctx(tmp_path, make_transport([]), run_id="r2")
    out = asyncio.run(run_batch(other, [_item()], qs))
    assert out["cache_hits"] == 1 and out["new_requests"] == 0
    third = make_ctx(tmp_path, make_transport([]), run_id="r3")
    changed = _item(state={"problem": "a different problem"})
    out = asyncio.run(run_batch(third, [changed], qs))
    assert out["cache_hits"] == 0 and out["new_requests"] == 1


def test_plain_item_still_builds_state(tmp_path):
    from atlas.inference.questions import load_question_set

    qs = load_question_set("screen", 0)
    item = {
        "comment_id": 9_000_000_102,
        "comment": "plain text",
        "parent": "",
        "story_title": "T",
        "thread_type": "story",
        "sentences": ["plain text"],
    }
    seen = []
    out = asyncio.run(
        run_batch(make_ctx(tmp_path, make_transport([], seen)), [item], qs)
    )
    assert out["completed"] == 1
    assert json.loads(seen[0].content)["state"]["comment"] == "plain text"

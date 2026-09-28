"""Task 11.1b: a question-set JSON may set "parent_limit"; the runner truncates
`parent` to that many characters for that set. Default stays 1500."""

import asyncio
import json

from atlas import paths
from atlas.inference.questions import load_question_set
from atlas.inference.runner import run_batch
from tests.cards.test_engine_support import make_ctx, make_transport

PARENT = "p" * 2000


def _write_qs(configs, parent_limit=None):
    qdir = configs / "questions"
    qdir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "x",
        "version": 1,
        "state_fields": ["comment", "parent"],
        "questions": {
            "q": {
                "type": "noul",
                "instructions": "?",
                "criteria": {"true": "y", "false": "n"},
            }
        },
    }
    if parent_limit is not None:
        data["parent_limit"] = parent_limit
    (qdir / "x.v1.json").write_text(json.dumps(data), encoding="utf-8")


def _item():
    return {
        "comment_id": 9_000_000_201,
        "comment": "short",
        "parent": PARENT,
        "story_title": "T",
        "thread_type": "story",
        "sentences": ["short"],
    }


def _parent_len(tmp_path, monkeypatch, parent_limit):
    configs = tmp_path / f"cfgs-{parent_limit}"
    _write_qs(configs, parent_limit)
    monkeypatch.setattr(paths, "CONFIGS", configs)
    qs = load_question_set("x", 1)
    seen = []
    ctx = make_ctx(tmp_path / str(parent_limit), make_transport(seen=seen))
    asyncio.run(run_batch(ctx, [_item()], qs))
    return qs, json.loads(seen[0].content)


def test_parent_limit_from_question_file(tmp_path, monkeypatch):
    qs, body = _parent_len(tmp_path, monkeypatch, 600)
    assert qs.parent_limit == 600
    assert len(body["state"]["parent"]) == 600


def test_parent_limit_defaults_to_1500(tmp_path, monkeypatch):
    qs, body = _parent_len(tmp_path, monkeypatch, None)
    assert qs.parent_limit == 1500
    assert len(body["state"]["parent"]) == 1500


def test_parent_limit_changes_question_set_sha(tmp_path, monkeypatch):
    qs_a, _ = _parent_len(tmp_path, monkeypatch, 600)
    qs_b, _ = _parent_len(tmp_path, monkeypatch, 700)
    assert qs_a.sha256 != qs_b.sha256

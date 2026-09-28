import ast
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from atlas import paths
from atlas.evaluation.queue import save_queue

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src/atlas/evaluation/labeler_app.py"


def test_labeler_never_reads_model_output_or_runs():
    tree = ast.parse(SRC.read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "RUNS" not in names and "run_dir" not in names
    assert not any("answers" in s for s in strings)


@pytest.fixture
def label_env(tmp_path, monkeypatch):
    labels_dir = tmp_path / "labels"
    configs = tmp_path / "configs"
    (configs / "questions").mkdir(parents=True)
    shutil.copy(
        REPO / "configs" / "questions" / "screen.v0.json",
        configs / "questions" / "screen.v0.json",
    )
    (configs / "rubric.v1.md").write_text(
        "---\nstatus: approved\nversion: v9\n---\n\n# test rubric\n", encoding="utf-8"
    )
    monkeypatch.setattr(paths, "LABELS", labels_dir)
    monkeypatch.setattr(paths, "CONFIGS", configs)

    items_mod = ModuleType("atlas.sources.items")

    def load_items(snapshot_dir, comment_ids):
        return [
            {
                "comment_id": int(cid),
                "comment": f"synthetic comment text for {cid}",
                "parent": f"synthetic parent text for {cid}",
                "story_title": f"Synthetic Story {cid}",
                "thread_type": "story",
                "sentences": [f"synthetic comment text for {cid}"],
                "text_sha256": "0" * 64,
            }
            for cid in comment_ids
        ]

    items_mod.load_items = load_items
    monkeypatch.setitem(sys.modules, "atlas.sources.items", items_mod)

    queue = {
        "ids": [9_000_000_001, 9_000_000_002],
        "repeats": [9_000_000_001],
        "bands": {},
        "rates": {},
        "seed": 1,
        "domain_ids": [9_000_000_001],
        "label_set": "calibration",
    }
    qpath = tmp_path / "queues" / "calibration.json"
    save_queue(queue, qpath)
    monkeypatch.setenv("ATLAS_LABEL_SET", "calibration")
    monkeypatch.setenv("ATLAS_QUEUE_PATH", str(qpath))
    monkeypatch.setenv("ATLAS_SNAPSHOT_ID", "snap-test")
    monkeypatch.setenv("ATLAS_REVIEWER", "tester")
    return labels_dir


def _radio(at, label):
    return next(r for r in at.radio if r.label == label)


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _set_and_save(at, values):
    for label, value in values.items():
        _radio(at, label).set_value(value)
    at.run()
    _button(at, "Save and next").click()
    at.run()


def test_labeler_saves_primary_and_repeat(label_env):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(SRC))
    at.run()
    assert not at.exception
    assert any("Synthetic Story 9000000001" in h.value for h in at.subheader)
    assert _button(at, "Save and next").disabled
    # First item is in domain_ids: three radios.
    assert len(at.radio) == 3
    _set_and_save(
        at,
        {
            "firsthand problem": "yes",
            "account type": "firsthand_account",
            "domain": "software_development",
        },
    )
    at.run()

    assert any("Synthetic Story 9000000002" in h.value for h in at.subheader)
    assert len(at.radio) == 2  # not in domain_ids
    _set_and_save(
        at,
        {"firsthand problem": "no", "account type": "general_opinion"},
    )
    at.run()

    rows = [
        json.loads(line)
        for line in (label_env / "labels.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 5
    by_q = {(r["comment_id"], r["question_id"]): r["value"] for r in rows}
    assert by_q[(9_000_000_001, "firsthand_problem")] == "yes"
    assert by_q[(9_000_000_001, "account_type")] == "firsthand_account"
    assert by_q[(9_000_000_001, "domain")] == "software_development"
    assert by_q[(9_000_000_002, "firsthand_problem")] == "no"
    assert by_q[(9_000_000_002, "account_type")] == "general_opinion"
    assert all(r["rubric_version"] == "v9" and r["reviewer"] == "tester" for r in rows)

    # A fresh session resumes at the first unlabeled position: the repeat view.
    at2 = AppTest.from_file(str(SRC))
    at2.run()
    assert not at2.exception
    assert any("Synthetic Story 9000000001" in h.value for h in at2.subheader)
    assert all(r.value is None for r in at2.radio)  # repeats never pre-fill
    assert len(at2.radio) == 2  # no domain radio on repeat views
    _set_and_save(
        at2,
        {"firsthand problem": "yes", "account type": "firsthand_account"},
    )
    repeat_rows = [
        json.loads(line)
        for line in (label_env / "repeats.jsonl").read_text().splitlines()
    ]
    assert len(repeat_rows) == 2
    assert {r["question_id"] for r in repeat_rows} == {
        "firsthand_problem",
        "account_type",
    }
    assert all(r["comment_id"] == 9_000_000_001 for r in repeat_rows)
    assert all(r["reviewer"] == "tester" for r in repeat_rows)

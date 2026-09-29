"""Task 16.1: per-mode label-set validation in the label store."""

import pytest

from atlas.evaluation.modes import MODES, get
from atlas.evaluation.store import LabelStore, allowed_values

BASE = 9_000_000_000


def _add(store, label_set, question_id, value, i=0):
    return store.add(
        comment_id=BASE + i,
        label_set=label_set,
        question_id=question_id,
        value=value,
        rubric_version="v1",
        reviewer="test",
        started_at="t0",
        ended_at="t1",
        seconds=1.0,
    )


def test_modes_registry():
    assert set(MODES) == {
        "facet_audit",
        "assignment_audit",
        "merge_audit",
        "interview",
    }
    for name, mod in MODES.items():
        assert mod.LABEL_SET == name
        assert mod.questions() == mod.QUESTIONS
        assert mod.questions() is not mod.QUESTIONS
        assert get(name) is mod
    assert get("calibration") is None and get(None) is None
    assert MODES["facet_audit"].NEEDS_TEXT is True
    assert MODES["assignment_audit"].NEEDS_TEXT is False
    assert MODES["merge_audit"].NEEDS_TEXT is False
    assert MODES["interview"].NEEDS_TEXT is False
    assert MODES["interview"].FREE_TEXT == {"why": 280}
    assert MODES["facet_audit"].FREE_TEXT == {}


def test_allowed_values_per_mode():
    assert allowed_values("facet_audit") == dict(MODES["facet_audit"].QUESTIONS)
    assert allowed_values("facet_audit")["resolution"] == (
        "resolved",
        "unresolved",
        "unclear",
    )
    assert allowed_values("assignment_audit") == {
        "fits": ("yes", "partly", "no", "unsure")
    }
    assert allowed_values("merge_audit") == {
        "same": ("same", "related", "different")
    }
    assert allowed_values("interview") == {
        "worth_interviewing": ("strong", "maybe", "no")
    }
    # Non-mode label sets keep the screen-based behavior.
    assert "firsthand_problem" in allowed_values("calibration")
    assert "firsthand_problem" in allowed_values()


def test_every_mode_value_accepted(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    i = 0
    for label_set, mod in MODES.items():
        for qid, values in mod.QUESTIONS.items():
            for value in values:
                _add(store, label_set, qid, value, i)
                i += 1
    assert len(store.all_rows()) == i


def test_unknown_value_rejected_per_mode(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    for label_set, mod in MODES.items():
        qid = next(iter(mod.QUESTIONS))
        with pytest.raises(ValueError):
            _add(store, label_set, qid, "bogus-value")


def test_unknown_question_rejected(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    with pytest.raises(ValueError):
        _add(store, "facet_audit", "fits", "yes")
    with pytest.raises(ValueError):
        _add(store, "calibration", "fits", "yes")


def test_interview_free_text(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    _add(store, "interview", "why", "x" * 280)
    with pytest.raises(ValueError):
        _add(store, "interview", "why", "x" * 281)
    with pytest.raises(ValueError):
        _add(store, "interview", "why", 5)
    # Free text is a labelable question but not a radio option set.
    assert "why" not in allowed_values("interview")


def test_calibration_still_works(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    row = _add(store, "calibration", "firsthand_problem", "yes")
    assert row["value"] == "yes"
    with pytest.raises(ValueError):
        _add(store, "calibration", "firsthand_problem", "strong")

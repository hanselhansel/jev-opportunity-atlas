import json

from atlas.inference.questions import (
    build_state,
    canonical_json,
    load_question_set,
    questions_for,
)


def test_load_and_version_label():
    qs = load_question_set("screen", 0)
    assert qs.label == "screen@0" and "firsthand_problem" in qs.questions
    assert len(qs.sha256) == 64


def test_sentence_marker_expands_per_comment():
    qs = load_question_set("deep", 0)
    q = questions_for(qs, sentences=["A.", "B.", "C."])
    assert q["support_sentence"]["criteria"] == {"s0": None, "s1": None, "s2": None}
    assert qs.questions["support_sentence"]["criteria"] == "SENTENCE_IDS"  # original untouched


def test_state_truncates_parent_and_labels_sentences():
    st = build_state(comment="C", parent="p" * 2000, story_title="T", thread_type="ask_hn",
                     sentences=["One.", "Two."], fields=["comment", "parent", "story_title", "thread_type", "sentences"])
    assert len(st["parent"]) == 1500 and st["sentences"] == {"s0": "One.", "s1": "Two."}


def test_state_includes_only_requested_fields():
    st = build_state(comment="C", parent=None, story_title="T", thread_type="story",
                     sentences=["x"], fields=["comment", "story_title"])
    assert st == {"comment": "C", "story_title": "T"}


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == canonical_json({"a": [2, {"c": 2, "d": 1}], "b": 1})
    assert json.loads(canonical_json({"x": "é"})) == {"x": "é"}

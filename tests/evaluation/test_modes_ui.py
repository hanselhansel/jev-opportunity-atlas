"""Task 16.3: static blindness checks plus AppTest coverage per labeler mode."""

import ast
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from atlas import paths
from atlas.evaluation import modes
from atlas.evaluation.queue import save_queue
from tests.evaluation.test_modes_support import BASE, make_env

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src/atlas/evaluation/labeler_app.py"
MODES_DIR = REPO / "src/atlas/evaluation/modes"
MODE_FILES = {
    p.stem: p for p in MODES_DIR.glob("*.py") if p.stem != "__init__"
}


def _tree(path):
    return ast.parse(path.read_text())


def _strings(tree):
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _names(tree):
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }


def test_every_mode_has_render_and_questions():
    assert set(MODE_FILES) == {
        "facets",
        "assignment",
        "merge",
        "interview",
    }
    for mod in modes.MODES.values():
        assert callable(mod.render)
        assert callable(mod.questions)
        assert mod.questions() == mod.QUESTIONS


def test_streamlit_imported_inside_functions_only():
    for path in MODE_FILES.values():
        tree = _tree(path)
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert not any(
                    a.name == "streamlit" for a in node.names
                ), path
            if isinstance(node, ast.ImportFrom):
                assert "streamlit" not in (node.module or ""), path


def test_no_blindness_breaking_tokens():
    for path in [SRC, *MODE_FILES.values()]:
        tree = _tree(path)
        strings = _strings(tree)
        names = _names(tree)
        assert "hidden" not in strings, path
        for token in ("is_jev", "jev_card_id", "shown_card_id"):
            assert not any(token in s for s in strings), (path, token)
            assert token not in names, (path, token)


def test_facets_mode_never_touches_model_output():
    tree = _tree(MODES_DIR / "facets.py")
    assert not any("answers" in s for s in _strings(tree))
    assert not _names(tree) & {"RUNS", "run_dir", "read_answers"}


def test_assignment_mode_has_no_leak_strings():
    tree = _tree(MODES_DIR / "assignment.py")
    for s in _strings(tree):
        assert "jev" not in s.lower()
        assert "assigned" not in s.lower()


@pytest.fixture
def label_env(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch)

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
    monkeypatch.setenv("ATLAS_SNAPSHOT_ID", "snap-test")
    monkeypatch.setenv("ATLAS_REVIEWER", "tester")
    return tmp_path


def _queue(tmp_path, monkeypatch, label_set, ids, repeats, items, blind=None):
    queue = {
        "label_set": label_set,
        "ids": ids,
        "repeats": repeats,
        "bands": {},
        "rates": {},
        "seed": 1,
        "items": items,
        "hidden": blind or {},
    }
    qpath = tmp_path / "queues" / f"{label_set}.json"
    save_queue(queue, qpath)
    monkeypatch.setenv("ATLAS_LABEL_SET", label_set)
    monkeypatch.setenv("ATLAS_QUEUE_PATH", str(qpath))
    return queue


def _labels(tmp_path):
    path = paths.LABELS / "labels.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _fill_radios(at):
    for r in at.radio:
        r.set_value(r.options[0])
    at.run()


def _rendered_text(at):
    texts = []
    for attr in ("markdown", "caption", "subheader", "header", "title"):
        texts += [e.value for e in getattr(at, attr)]
    for r in at.radio:
        texts.append(r.label)
        texts += list(r.options or [])
    for w in at.text_input:
        texts.append(w.label)
    for b in at.button:
        texts.append(b.label)
    for e in at.expander:
        texts.append(e.label)
    return texts


def test_calibration_has_comment_heading(label_env, monkeypatch):
    from streamlit.testing.v1 import AppTest

    ids = [BASE + 1]
    _queue(label_env, monkeypatch, "calibration", ids, [], {})
    at = AppTest.from_file(str(SRC))
    at.run()
    assert not at.exception
    marks = [m.value for m in at.markdown]
    head = marks.index("#### Comment")
    text = marks.index(f"synthetic comment text for {ids[0]}")
    assert head < text


def test_facet_mode_flow_and_repeat_resume(label_env, monkeypatch):
    from streamlit.testing.v1 import AppTest

    ids = [BASE + 1, BASE + 2]
    _queue(
        label_env,
        monkeypatch,
        "facet_audit",
        ids,
        [ids[0]],
        {str(c): {"comment_id": c} for c in ids},
    )
    at = AppTest.from_file(str(SRC))
    at.run()
    assert not at.exception
    assert any(
        f"Synthetic Story {ids[0]}" in h.value for h in at.subheader
    )
    assert "#### Comment" in [m.value for m in at.markdown]
    assert f"synthetic parent text for {ids[0]}" in [
        m.value for m in at.expander[0].markdown
    ]
    assert len(at.radio) == 7
    assert _button(at, "Save and next").disabled

    _fill_radios(at)
    _button(at, "Save and next").click()
    at.run()
    _fill_radios(at)
    _button(at, "Save and next").click()
    at.run()

    rows = _labels(label_env)
    assert len(rows) == 14
    assert all(r["label_set"] == "facet_audit" for r in rows)
    assert {r["comment_id"] for r in rows} == set(ids)

    at2 = AppTest.from_file(str(SRC))
    at2.run()
    assert not at2.exception
    assert len(at2.radio) == 7
    assert all(r.value is None for r in at2.radio)  # repeats never pre-fill


def test_assignment_mode_never_reveals_the_pick(label_env, monkeypatch):
    from streamlit.testing.v1 import AppTest

    ids = [BASE + 10, BASE + 11]
    items = {
        str(ids[0]): {
            "comment_id": ids[0],
            "pain_sentence": "synthetic pain one",
            "card_statement": "Synthetic need alpha",
        },
        str(ids[1]): {
            "comment_id": ids[1],
            "pain_sentence": "synthetic pain two",
            "card_statement": "Synthetic need beta",
        },
    }
    blind = {
        str(ids[0]): {"jev_card_id": "c0001", "shown_card_id": "c0001",
                      "is_jev": True, "forced": False},
        str(ids[1]): {"jev_card_id": "c0001", "shown_card_id": "c0002",
                      "is_jev": False, "forced": False},
    }
    _queue(label_env, monkeypatch, "assignment_audit", ids, [], items, blind)
    at = AppTest.from_file(str(SRC))
    at.run()
    assert not at.exception
    assert len(at.radio) == 1 and at.radio[0].label == "fits"
    assert list(at.radio[0].options) == ["yes", "partly", "no", "unsure"]
    for text in _rendered_text(at):
        assert "jev" not in text.lower()
        assert "assigned" not in text.lower()
    assert "synthetic pain one" in [
        m.value.lstrip("> ") for m in at.markdown
    ]

    at.radio[0].set_value("partly")
    at.run()
    _button(at, "Save and next").click()
    at.run()
    rows = _labels(label_env)
    assert len(rows) == 1
    assert rows[0]["question_id"] == "fits" and rows[0]["value"] == "partly"
    assert rows[0]["comment_id"] == ids[0]
    assert rows[0]["label_set"] == "assignment_audit"

    for text in _rendered_text(at):
        assert "jev" not in text.lower()
        assert "assigned" not in text.lower()


def test_merge_mode_render(label_env, monkeypatch):
    from streamlit.testing.v1 import AppTest

    ids = [BASE + 20]
    items = {
        str(ids[0]): {
            "card_a": "Synthetic need alpha",
            "card_b": "Synthetic need beta",
        }
    }
    blind = {
        str(ids[0]): {"card_a": "c0001", "card_b": "c0002", "expected": 1.9}
    }
    _queue(label_env, monkeypatch, "merge_audit", ids, [], items, blind)
    at = AppTest.from_file(str(SRC))
    at.run()
    assert not at.exception
    assert [r.label for r in at.radio] == ["same"]
    assert list(at.radio[0].options) == ["same", "related", "different"]
    marks = [m.value for m in at.markdown]
    assert "#### Need A" in marks and "#### Need B" in marks
    assert "Synthetic need alpha" in marks
    assert "Synthetic need beta" in marks


def test_interview_mode_render_and_free_text(label_env, monkeypatch):
    from streamlit.testing.v1 import AppTest

    ids = [BASE + 30, BASE + 31]
    items = {
        str(i): {
            "statement": f"Synthetic need {i}",
            "group_label": "Synthetic group one",
            "examples": ["synthetic example one", "synthetic example two"],
            "metrics": {
                "authors": 10,
                "threads": 2,
                "periods": 3,
                "domains": 4,
            },
        }
        for i in ids
    }
    blind = {str(i): {"card_id": "c0001"} for i in ids}
    _queue(label_env, monkeypatch, "interview", ids, [], items, blind)
    at = AppTest.from_file(str(SRC))
    at.run()
    assert not at.exception
    assert any("not a blind check" in c.value for c in at.caption)
    assert [r.label for r in at.radio] == ["worth interviewing"]
    assert len(at.text_input) == 1
    assert "280" in at.text_input[0].label
    marks = [m.value for m in at.markdown]
    assert "authors 10 · threads 2 · periods 3 · domains 4" in marks
    assert "> synthetic example one" in marks

    at.radio[0].set_value("strong")
    at.text_input[0].set_value("synthetic reason")
    at.run()
    _button(at, "Save and next").click()
    at.run()
    rows = _labels(label_env)
    assert {(r["question_id"], r["value"]) for r in rows} == {
        ("worth_interviewing", "strong"),
        ("why", "synthetic reason"),
    }
    assert all(r["comment_id"] == ids[0] for r in rows)

    # Next item: empty free text saves only the radio row.
    at.radio[0].set_value("maybe")
    at.run()
    _button(at, "Save and next").click()
    at.run()
    rows = _labels(label_env)
    assert len(rows) == 3
    assert {r["question_id"] for r in rows if r["comment_id"] == ids[1]} == {
        "worth_interviewing"
    }
    assert any("labeled" in s.value for s in at.success)

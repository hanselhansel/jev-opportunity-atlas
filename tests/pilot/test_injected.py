"""Task 7.4: injected-instruction cases and their screen/facet runs."""

import json

import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.pilot import injected
from tests.pilot.test_support import (  # noqa: F401
    answers_table,
    make_transport,
    mock_env,
    pilot_repo,
)

RUN_ID = "pilot-7"


def test_injected_cases_config_shape(pilot_repo):  # noqa: F811
    cfg = json.loads(
        (paths.CONFIGS / "pilot" / "injected_cases.json").read_text()
    )
    cases = injected.load_cases()
    assert len(cases) == 20
    ids = [c["comment_id"] for c in cases]
    assert len(set(ids)) == 20
    assert min(ids) >= 9_100_000_000
    assert set(cfg["case_types"]) == {c["case_type"] for c in cases}
    for c in cases:
        assert c["comment"] == " ".join(c["sentences"])
        assert set(c["expected"]) == {"firsthand_problem"}
        assert c["expected"]["firsthand_problem"] in ("yes", "no")
        for field in (
            "case_type",
            "sentences",
            "comment",
            "parent",
            "story_title",
            "thread_type",
        ):
            assert field in c


def test_case_items_build_runner_items(pilot_repo):  # noqa: F811
    cases = injected.load_cases()
    items = injected.case_items(cases)
    assert len(items) == len(cases)
    for item, case in zip(items, cases):
        assert item["comment_id"] == case["comment_id"]
        assert item["comment"] == case["comment"]
        assert item["sentences"] == case["sentences"]
        assert item["parent"] == case["parent"]
        assert item["thread_type"] == case["thread_type"]


def test_injected_accuracy_hand_built():
    cases = [
        {
            "comment_id": 9_100_000_001,
            "case_type": "t1",
            "expected": {"firsthand_problem": "yes"},
        },
        {
            "comment_id": 9_100_000_002,
            "case_type": "t1",
            "expected": {"firsthand_problem": "no"},
        },
        {
            "comment_id": 9_100_000_003,
            "case_type": "t2",
            "expected": {"firsthand_problem": "yes"},
        },
        {
            "comment_id": 9_100_000_004,
            "case_type": "t2",
            "expected": {"firsthand_problem": "no"},
        },
    ]
    answers = answers_table(
        [
            (9_100_000_001, "firsthand_problem", 0.9),  # yes, correct
            (9_100_000_002, "firsthand_problem", 0.9),  # yes, wrong
            (9_100_000_003, "firsthand_problem", 0.7),  # yes, correct
            (9_100_000_001, "other_question", 0.1),  # ignored
        ],
        question_set="screen@1",
    )
    # case 4 has no answer -> incorrect and counted as missing.
    res = injected.injected_accuracy(answers, cases)
    assert res["overall"] == {
        "n": 4,
        "correct": 2,
        "missing": 1,
        "accuracy": 0.5,
    }
    assert res["by_type"]["t1"] == {
        "n": 2,
        "correct": 1,
        "missing": 0,
        "accuracy": 0.5,
    }
    assert res["by_type"]["t2"] == {
        "n": 2,
        "correct": 1,
        "missing": 1,
        "accuracy": 0.5,
    }


def test_run_injected_dry_run(pilot_repo, monkeypatch, capsys):  # noqa: F811
    from atlas.inference import keys
    from atlas.pilot import stages

    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(stages, "_transport", lambda: pytest.fail("transport"))
    out = injected.run_injected(RUN_ID)
    assert out["dispatched"] is False
    captured = capsys.readouterr().out
    assert '"question_set": "screen@1"' in captured
    assert '"question_set": "facets@1"' in captured
    assert [e["question_set"] for e in out["estimates"]] == [
        "screen@1",
        "facets@1",
    ]
    assert all(e["calls"] == 20 for e in out["estimates"])
    assert not paths.run_dir(f"{RUN_ID}-injected").exists()


def test_run_injected_end_to_end(pilot_repo, monkeypatch, capsys):  # noqa: F811
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    out = injected.run_injected(RUN_ID, yes=True)
    assert out["dispatched"] is True
    assert len(seen) == 40  # 20 cases x screen@1 + facets@1
    assert set(out["runs"]) == {"screen@1", "facets@1"}
    run_dir = paths.run_dir(f"{RUN_ID}-injected")
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["budget"] == "pilot"
    assert [e["label"] for e in manifest["question_sets"]] == [
        "screen@1",
        "facets@1",
    ]
    rows = pq.read_table(run_dir / "answers").to_pylist()
    assert {r["question_set"] for r in rows} == {"screen@1", "facets@1"}
    case_ids = {c["comment_id"] for c in injected.load_cases()}
    assert {r["comment_id"] for r in rows} == case_ids

    # The accuracy report reads the run's answers table end to end.
    res = injected.injected_accuracy(
        pq.read_table(run_dir / "answers"), injected.load_cases()
    )
    assert res["overall"]["n"] == 20
    assert res["overall"]["missing"] == 0
    assert set(res["by_type"]) == {
        "override_yes",
        "genuine_override_no",
        "disguised_pitch",
        "fake_label",
    }

"""Task 18.3: benchmark scoring against hand-built answers, packed map,
assignments, and benchmark.json — every section checked for exact numbers,
including a missing answer and a "none" card case."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.benchmark.score import score_benchmark, write_report
from atlas.cards.engine.assign import AssignResult, write_assignments
from atlas.pilot import packed
from tests.benchmark.test_support import (
    answer_row,
    bench_configs,
    write_answers,
    write_benchmark_json,
)
from tests.pilot.test_support import pilot_repo  # noqa: F401

RUN_ID = "r1"
C1, C2, C3, C4, C5, C6, C7 = (9400000001 + i for i in range(7))
PACK1, PACK2 = 9900000001, 9900000002
SCREEN, FACETS2, PACKED = "screen@1", "facets@2", packed.PACKED_LABEL

SCORE_CASES = {
    "version": 1,
    "note": "score test cases",
    "cases": [
        {
            "id": C1,
            "category": "genuine_firsthand",
            "text": "synthetic one",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "workaround": "yes",
                "resolution": "resolved",
            },
            "why": "t",
        },
        {
            "id": C2,
            "category": "general_opinion",
            "text": "synthetic two",
            "expected": {
                "firsthand_problem": "no",
                "account_type": "general_opinion",
            },
            "why": "t",
        },
        {
            "id": C3,
            "category": "secondhand",
            "text": "synthetic three",
            "expected": {
                "firsthand_problem": "no",
                "account_type": "secondhand_report",
                "paid": "yes",
            },
            "why": "t",
        },
        {
            "id": C4,
            "category": "genuine_firsthand",
            "text": "synthetic four",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "paid": "no",
            },
            "why": "t",
        },
        {
            "id": C5,
            "category": "card_placement",
            "text": "synthetic five",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "card": "c01",
            },
            "why": "t",
        },
        {
            "id": C6,
            "category": "card_placement",
            "text": "synthetic six",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "card": "none",
            },
            "why": "t",
        },
        {
            "id": C7,
            "category": "card_placement",
            "text": "synthetic seven",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "card": "c12",
            },
            "why": "t",
        },
    ],
}

ANSWER_ROWS = [
    answer_row(RUN_ID, C1, SCREEN, "firsthand_problem", noul=0.8),
    answer_row(RUN_ID, C1, SCREEN, "account_type", choice="firsthand_account",
               probs={"firsthand_account": 0.9, "other": 0.1}, confidence=0.9),
    answer_row(RUN_ID, C2, SCREEN, "firsthand_problem", noul=0.6),
    answer_row(RUN_ID, C2, SCREEN, "account_type", choice="general_opinion",
               probs={"general_opinion": 0.88}, confidence=0.88),
    answer_row(RUN_ID, C3, SCREEN, "firsthand_problem", noul=0.2),
    answer_row(RUN_ID, C3, SCREEN, "account_type", choice="firsthand_account",
               probs={"firsthand_account": 0.77}, confidence=0.77),
    # C4 has no screen@1 answers at all: the missing-answer case.
    answer_row(RUN_ID, C5, SCREEN, "firsthand_problem", noul=0.9),
    answer_row(RUN_ID, C5, SCREEN, "account_type", choice="firsthand_account",
               confidence=0.9),
    answer_row(RUN_ID, C6, SCREEN, "firsthand_problem", noul=0.7),
    answer_row(RUN_ID, C6, SCREEN, "account_type", choice="firsthand_account",
               confidence=0.9),
    answer_row(RUN_ID, C7, SCREEN, "firsthand_problem", noul=0.55),
    answer_row(RUN_ID, C7, SCREEN, "account_type", choice="firsthand_account",
               confidence=0.9),
    answer_row(RUN_ID, PACK1, PACKED, "c1_firsthand_problem", noul=0.4),
    answer_row(RUN_ID, PACK1, PACKED, "c2_firsthand_problem", noul=0.2),
    answer_row(RUN_ID, PACK1, PACKED, "c3_firsthand_problem", noul=0.6),
    answer_row(RUN_ID, PACK1, PACKED, "c4_firsthand_problem", noul=0.9),
    answer_row(RUN_ID, PACK1, PACKED, "c5_firsthand_problem", noul=0.8),
    answer_row(RUN_ID, PACK2, PACKED, "c1_firsthand_problem", noul=0.3),
    answer_row(RUN_ID, PACK2, PACKED, "c2_firsthand_problem", noul=0.8),
    answer_row(RUN_ID, C1, FACETS2, "workaround", noul=0.6),
    answer_row(RUN_ID, C1, FACETS2, "resolution", choice="resolved",
               confidence=0.91),
    answer_row(RUN_ID, C3, FACETS2, "paid", noul=0.4),
]

PACKED_MAP = [
    {"packed_id": PACK1, "slot": f"c{i}", "comment_id": cid}
    for i, cid in enumerate((C1, C2, C3, C4, C5), start=1)
] + [
    {"packed_id": PACK2, "slot": f"c{i}", "comment_id": cid}
    for i, cid in enumerate((C6, C7), start=1)
]

ASSIGNMENT_ROWS = [
    {  # wrong card in the right group
        "run_id": RUN_ID, "comment_id": C5, "taxonomy_version": "t1",
        "group_id": "g01", "group_p": 0.9, "group_confidence": 0.9,
        "card_id": "c02", "card_p": 0.5, "card_confidence": 0.5,
        "verified_p": None,
    },
    {  # expected "none", got none
        "run_id": RUN_ID, "comment_id": C6, "taxonomy_version": "t1",
        "group_id": "none", "group_p": 0.9, "group_confidence": 0.9,
        "card_id": None, "card_p": None, "card_confidence": None,
        "verified_p": None,
    },
    {  # expected a real card, got none in the right group
        "run_id": RUN_ID, "comment_id": C7, "taxonomy_version": "t1",
        "group_id": "g03", "group_p": 0.8, "group_confidence": 0.8,
        "card_id": "none", "card_p": None, "card_confidence": 0.4,
        "verified_p": None,
    },
]

WANT_MISSES = [
    {"case_id": C3, "category": "secondhand", "question": "account_type",
     "expected": "secondhand_report", "got": "firsthand_account", "p": 0.77},
    {"case_id": C4, "category": "genuine_firsthand",
     "question": "account_type", "expected": "firsthand_account",
     "got": None, "p": None},
    {"case_id": C5, "category": "card_placement", "question": "card",
     "expected": "c01", "got": "c02", "p": 0.5},
    {"case_id": C7, "category": "card_placement", "question": "card",
     "expected": "c12", "got": "none", "p": None},
    {"case_id": C1, "category": "genuine_firsthand",
     "question": "firsthand_problem/packed", "expected": "yes", "got": "no",
     "p": 0.4},
    {"case_id": C3, "category": "secondhand",
     "question": "firsthand_problem/packed", "expected": "no", "got": "yes",
     "p": 0.6},
    {"case_id": C6, "category": "card_placement",
     "question": "firsthand_problem/packed", "expected": "yes", "got": "no",
     "p": 0.3},
    {"case_id": C2, "category": "general_opinion",
     "question": "firsthand_problem/single", "expected": "no", "got": "yes",
     "p": 0.6},
    {"case_id": C4, "category": "genuine_firsthand",
     "question": "firsthand_problem/single", "expected": "yes", "got": None,
     "p": None},
    {"case_id": C3, "category": "secondhand", "question": "paid",
     "expected": "yes", "got": "no", "p": 0.4},
    {"case_id": C4, "category": "genuine_firsthand", "question": "paid",
     "expected": "no", "got": None, "p": None},
]


@pytest.fixture
def score_repo(pilot_repo):  # noqa: F811
    bench_configs(pilot_repo, SCORE_CASES)
    run_dir = paths.run_dir(RUN_ID)
    write_benchmark_json(RUN_ID, n_cases=len(SCORE_CASES["cases"]))
    write_answers(RUN_ID, ANSWER_ROWS)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(PACKED_MAP, schema=packed.PACKED_MAP),
        run_dir / "packed_map.parquet",
    )
    write_assignments(run_dir, AssignResult(rows=ASSIGNMENT_ROWS), "t1")
    return pilot_repo


def test_score_firsthand_thresholds(score_repo):
    s = score_benchmark(RUN_ID)
    assert s["run_id"] == "r1"
    assert s["cases_version"] == "v1"
    assert s["n_cases"] == 7
    assert s["disclaimer"] == (
        "Synthetic benchmark (invented cases; not real-data accuracy)"
    )

    m = s["firsthand"]["single"]["0.5"]
    assert m["n"] == 7 and m["n_missing"] == 1
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (4, 1, 1, 1)
    assert m["accuracy"] == pytest.approx(5 / 7)
    assert m["precision"] == pytest.approx(0.8)
    assert m["recall"] == pytest.approx(0.8)

    m = s["firsthand"]["single"]["0.7"]
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (3, 0, 2, 2)
    assert m["accuracy"] == pytest.approx(5 / 7)
    assert m["precision"] == 1.0
    assert m["recall"] == pytest.approx(0.6)
    assert m["n_missing"] == 1

    m = s["firsthand"]["packed"]["0.5"]
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (3, 1, 2, 1)
    assert m["n_missing"] == 0
    assert m["accuracy"] == pytest.approx(4 / 7)
    assert m["precision"] == pytest.approx(0.75)
    assert m["recall"] == pytest.approx(0.6)

    m = s["firsthand"]["packed"]["0.7"]
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (3, 0, 2, 2)
    assert m["accuracy"] == pytest.approx(5 / 7)
    assert m["precision"] == 1.0
    assert m["recall"] == pytest.approx(0.6)


def test_score_by_category_account_type_facets(score_repo):
    s = score_benchmark(RUN_ID)
    assert s["by_category"]["single"] == {
        "card_placement": {"n": 3, "correct": 3, "accuracy": 1.0},
        "general_opinion": {"n": 1, "correct": 0, "accuracy": 0.0},
        "genuine_firsthand": {"n": 2, "correct": 1, "accuracy": 0.5},
        "secondhand": {"n": 1, "correct": 1, "accuracy": 1.0},
    }
    packed_cat = s["by_category"]["packed"]
    assert packed_cat["card_placement"] == {
        "n": 3, "correct": 2, "accuracy": pytest.approx(2 / 3),
    }
    assert packed_cat["secondhand"] == {
        "n": 1, "correct": 0, "accuracy": 0.0,
    }

    at = s["account_type"]
    assert at["n"] == 7 and at["correct"] == 5 and at["missing"] == 1
    assert at["accuracy"] == pytest.approx(5 / 7)

    facets = s["facets"]
    assert facets["workaround"] == {
        "n": 1, "correct": 1, "missing": 0, "accuracy": 1.0,
    }
    assert facets["paid"] == {
        "n": 2, "correct": 0, "missing": 1, "accuracy": 0.0,
    }
    assert facets["switched"] == {
        "n": 0, "correct": 0, "missing": 0, "accuracy": None,
    }
    assert facets["resolution"] == {
        "n": 1, "correct": 1, "missing": 0, "accuracy": 1.0,
    }


def test_score_cards_and_misses(score_repo):
    s = score_benchmark(RUN_ID)
    cards = s["cards"]
    assert cards["n"] == 3 and cards["correct"] == 1
    assert cards["top1_accuracy"] == pytest.approx(1 / 3)
    assert cards["none"] == {"n": 1, "correct": 1}
    assert cards["carded"] == {
        "n": 2, "correct": 0, "false_none": 1, "group_correct": 2,
    }
    assert s["misses"] == WANT_MISSES


def test_write_report_heading_and_files(score_repo):
    path = write_report(RUN_ID)
    run_dir = paths.run_dir(RUN_ID)
    assert path == run_dir / "benchmark_report.md"
    md = path.read_text(encoding="utf-8")
    lines = md.splitlines()
    assert lines[0] == (
        "# Synthetic benchmark (invented cases; not real-data accuracy)"
    )
    # "real-data accuracy" appears only inside the negated heading.
    assert [ln for ln in lines if "real-data accuracy" in ln] == [lines[0]]
    assert (run_dir / "benchmark_score.json").exists()
    saved = json.loads((run_dir / "benchmark_score.json").read_text())
    assert saved["n_cases"] == 7
    assert saved["firsthand"]["single"]["0.5"]["tp"] == 4

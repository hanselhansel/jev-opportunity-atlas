"""Task 18.2: benchmark runner — estimates first, then four dispatch stages
over a tiny synthetic cases file (never the real cases.v1.yaml)."""

import collections
import json
import re

import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.cards.engine.assign import load_assignments, read_answers
from atlas.pilot import packed
from tests.benchmark.test_support import bench_configs
from tests.pilot.test_support import (  # noqa: F401
    make_transport,
    mock_env,
    pilot_repo,
)

RUN_ID = "bench-1"

CASES = {
    "version": 1,
    "note": "tiny synthetic set for the runner test",
    "cases": [
        {
            "id": 9400000001,
            "category": "genuine_firsthand",
            "text": "PAIN our sync job drops rows every night.",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "workaround": "yes",
                "paid": "no",
                "resolution": "unresolved",
            },
            "why": "test",
        },
        {
            "id": 9400000002,
            "category": "general_opinion",
            "text": "Most monitoring tools are overpriced.",
            "expected": {
                "firsthand_problem": "no",
                "account_type": "general_opinion",
            },
            "why": "test",
        },
        {
            "id": 9400000003,
            "category": "secondhand",
            "text": "A coworker lost a week to a bad deploy.",
            "expected": {
                "firsthand_problem": "no",
                "account_type": "secondhand_report",
            },
            "why": "test",
        },
        {
            "id": 9400000004,
            "category": "genuine_firsthand",
            "text": "PAIN I rebuilt our CI pipeline twice this quarter.",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "switched": "yes",
            },
            "why": "test",
        },
        {
            "id": 9400000005,
            "category": "card_placement",
            "text": "PAIN our AI assistant invents API names.",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "card": "c01",
            },
            "why": "test",
        },
        {
            "id": 9400000006,
            "category": "card_placement",
            "text": "PAIN my toaster oven resets its clock every day.",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "card": "none",
            },
            "why": "test",
        },
        {
            "id": 9400000007,
            "category": "one_line_reaction",
            "text": "Same here.",
            "expected": {
                "firsthand_problem": "no",
                "account_type": "other",
            },
            "why": "test",
        },
    ],
}
N_CASES = len(CASES["cases"])
N_FACET = 2  # cases 1 and 4 carry facet expectations
N_CARD = 2  # cases 5 and 6 carry a card expectation


@pytest.fixture
def bench_repo(pilot_repo):  # noqa: F811
    """pilot_repo plus the real pilot.t1 cardset and the tiny cases file."""
    return bench_configs(pilot_repo, CASES)


_SLOT_QID = re.compile(r"^c\d+_")


def _classify(request) -> str:
    qids = set(json.loads(request.content)["questions"])
    if "firsthand_problem" in qids:
        return "single"
    if "group" in qids:
        return "group"
    if "card" in qids:
        return "card"
    if all(_SLOT_QID.match(q) for q in qids):
        return "packed"
    return "facets"


def test_estimate_only_makes_no_requests_and_writes_nothing(
    bench_repo, monkeypatch, capsys
):
    from atlas.benchmark import run as bench

    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    out = bench.run_benchmark(RUN_ID, yes=False)
    assert out["dispatched"] is False
    assert seen == []
    assert not paths.run_dir(RUN_ID).exists()
    labels = [e["question_set"] for e in out["estimates"]]
    assert labels == [
        "screen@1",
        packed.PACKED_LABEL,
        "facets@2",
        "assign-g@t1",
        "assign-c@t1",
    ]
    assert out["estimates"][0]["calls"] == N_CASES
    assert out["estimates"][2]["calls"] == N_FACET
    assert out["estimates"][3]["calls"] == N_CARD
    # Packed and card items carry their own state: bytes/3.2 path.
    assert out["estimates"][1]["method"] == "bytes/3.2"
    assert out["estimates"][3]["method"] == "bytes/3.2"
    assert out["total_usd"] == pytest.approx(
        sum(e["usd"] for e in out["estimates"])
    )
    assert "total_usd" in capsys.readouterr().out


def test_run_dispatches_all_four_stages(bench_repo, monkeypatch, capsys):
    from atlas.benchmark import run as bench

    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    out = bench.run_benchmark(RUN_ID, yes=True)
    assert out["dispatched"] is True
    counts = collections.Counter(_classify(r) for r in seen)
    assert counts == {
        "single": N_CASES,
        "packed": 2,  # ceil(7 / 5)
        "facets": N_FACET,
        "group": N_CARD,
        "card": N_CARD,  # first-option mock never picks "none"
    }

    run_dir = paths.run_dir(RUN_ID)
    single = read_answers(run_dir, "screen@1")
    assert set(single) == {c["id"] for c in CASES["cases"]}
    pmap = pq.read_table(run_dir / "packed_map.parquet")
    assert pmap.num_rows == N_CASES
    packed_answers = read_answers(run_dir, packed.PACKED_LABEL)
    assert len(packed_answers) == 2  # one entry per packed call
    result = load_assignments(run_dir, "t1")
    assert {r["comment_id"] for r in result.rows} == {9400000005, 9400000006}

    meta = json.loads((run_dir / "benchmark.json").read_text())
    assert meta["cases_version"] == "v1"
    assert meta["cases_sha256"] == bench.cases_sha256("v1")
    assert meta["n_cases"] == N_CASES
    assert meta["cardset"] == "pilot.t1"
    assert meta["pack_k"] == 5
    assert meta["budget"] == "discovery"
    assert set(out["runs"]) == {"screen", "packed", "facets", "cards"}


def test_case_selectors(bench_repo):
    from atlas.benchmark import run as bench

    cases = bench.load_cases("v1")
    assert len(cases) == N_CASES
    items = bench.case_items(cases)
    assert items[0]["comment_id"] == 9400000001
    assert items[0]["parent"] == "" and items[0]["thread_type"] == "story"
    assert items[0]["sentences"]
    assert {c["id"] for c in bench.facet_cases(cases)} == {
        9400000001,
        9400000004,
    }
    rows = bench.card_rows(cases)
    assert [r["comment_id"] for r in rows] == [9400000005, 9400000006]
    assert rows[0]["pain_sentence"] == CASES["cases"][4]["text"]

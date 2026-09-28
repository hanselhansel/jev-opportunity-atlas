"""Task 7.3: packed-call experiment — pack k comments per call, unpack answers,
compare against single-call results, and the pilot-<seed>-packed stage."""

import hashlib
import json
import math

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.pilot import packed, stages
from atlas.pilot.draw import pilot_draw
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    answers_table,
    ledger_row,
    make_transport,
    mock_env,
    pilot_repo,
    write_ledger,
)

SAMPLE_ID = "pilot-7"
RUN_ID = "pilot-7"
PACKED_RUN = "pilot-7-packed"


def _items(n, texts=None):
    return [
        {
            "comment_id": 9_000_000_001 + i,
            "comment": texts[i] if texts else f"synthetic comment {i}",
            "parent": "",
            "story_title": "T",
            "thread_type": "story",
            "sentences": [f"synthetic comment {i}"],
        }
        for i in range(n)
    ]


def test_packed_items_shape_and_wording(pilot_repo):  # noqa: F811
    from atlas.inference.questions import load_question_set

    items = _items(12)
    out, pmap = packed.packed_items(items, k=5)
    assert len(out) == 3
    assert [p["comment_id"] for p in out] == [
        9_000_000_001,
        9_000_000_006,
        9_000_000_011,
    ]
    assert out[0]["state"] == {
        f"c{j}": f"synthetic comment {j - 1}" for j in range(1, 6)
    }
    assert out[2]["state"] == {
        "c1": "synthetic comment 10",
        "c2": "synthetic comment 11",
    }
    assert out[0]["members"] == [9_000_000_001 + i for i in range(5)]
    assert out[2]["members"] == [9_000_000_011, 9_000_000_012]

    screen_q = load_question_set("screen", 1).questions["firsthand_problem"]
    assert "`comment`" in screen_q["instructions"]
    for j in (1, 2):
        for i, p in enumerate(out):
            q = p["questions"][f"c{j}_firsthand_problem"]
            assert q["type"] == screen_q["type"]
            assert f"`c{j}`" in q["instructions"]
            assert "`comment`" not in q["instructions"]
            if j <= len(p["members"]) - 1:
                pass
    # Slots that a short last chunk does not have are absent.
    assert list(out[2]["questions"]) == [
        "c1_firsthand_problem",
        "c2_firsthand_problem",
    ]
    # Questions are deep copies: editing one packed item leaves others intact.
    out[0]["questions"]["c1_firsthand_problem"]["instructions"] = "mutated"
    assert "`c1`" in out[1]["questions"]["c1_firsthand_problem"]["instructions"]

    rows = pmap.to_pylist()
    assert pmap.schema == packed.PACKED_MAP
    assert len(rows) == 12
    for i, r in enumerate(rows):
        assert r["slot"] == f"c{i % 5 + 1}"
        assert r["comment_id"] == 9_000_000_001 + i
        assert r["packed_id"] == 9_000_000_001 + 5 * (i // 5)


def test_packed_question_set(pilot_repo):  # noqa: F811
    from atlas.inference.questions import load_question_set

    qs = packed.packed_question_set(5)
    assert qs.name == "packed-screen"
    assert qs.version == 1 and qs.label == "packed-screen@1"
    assert qs.state_fields == [f"c{j}" for j in range(1, 6)]
    assert list(qs.questions) == [
        f"c{j}_firsthand_problem" for j in range(1, 6)
    ]
    screen = load_question_set("screen", 1)
    assert qs.sha256 == hashlib.sha256(
        f"{screen.sha256}:k=5".encode()
    ).hexdigest()
    assert qs.sha256 != packed.packed_question_set(4).sha256


def test_unpack_answers_maps_slots_to_members(pilot_repo):  # noqa: F811
    _out, pmap = packed.packed_items(_items(3), k=3)
    packed_id = 9_000_000_001
    answers = answers_table(
        [
            (packed_id, "c1_firsthand_problem", 0.9),
            (packed_id, "c2_firsthand_problem", 0.1),
            (packed_id, "c3_firsthand_problem", 0.5),
            (packed_id, "other_question", 0.7),  # not a slot id: dropped
        ],
        question_set="packed-screen@1",
    )
    out = packed.unpack_answers(answers, pmap)
    assert out.schema == packed.UNPACKED
    rows = sorted(out.to_pylist(), key=lambda r: r["comment_id"])
    assert rows == [
        {
            "comment_id": 9_000_000_001,
            "question_id": "firsthand_problem",
            "noul": 0.9,
        },
        {
            "comment_id": 9_000_000_002,
            "question_id": "firsthand_problem",
            "noul": 0.1,
        },
        {
            "comment_id": 9_000_000_003,
            "question_id": "firsthand_problem",
            "noul": 0.5,
        },
    ]


def test_ledger_tokens_filters_class_set_and_ids(tmp_path):
    path = write_ledger(
        tmp_path / "ledger.jsonl",
        [
            ledger_row(9_000_000_001, "screen@1", 100),
            ledger_row(9_000_000_002, "screen@1", 120),
            ledger_row(9_000_000_003, "screen@1", 999, cost_class="replay"),
            ledger_row(9_000_000_004, "screen@1", 888, cost_class="unknown"),
            ledger_row(9_000_000_005, "facets@1", 777),
            ledger_row(9_000_000_006, "screen@1", None),
        ],
    )
    assert packed.ledger_tokens(path, "screen@1") == 220.0
    assert packed.ledger_tokens(path, "screen@1", [9_000_000_001]) == 100.0
    assert packed.ledger_tokens(path, "facets@1") == 777.0


def test_compare_packed_metrics(tmp_path):
    cids = [9_000_000_001 + i for i in range(6)]
    single_noul = [0.9, 0.8, 0.1, 0.2, 0.95, 0.05]
    packed_noul = [0.9, 0.8, 0.1, 0.25, 0.9, 0.0]
    single = answers_table(
        [(c, "firsthand_problem", v) for c, v in zip(cids, single_noul)]
        + [(9_000_000_099, "firsthand_problem", 0.7)]  # unmatched: dropped
    )
    unpacked = pa.Table.from_pylist(
        [
            {"comment_id": c, "question_id": "firsthand_problem", "noul": v}
            for c, v in zip(cids, packed_noul)
        ],
        schema=packed.UNPACKED,
    )
    pmap = pa.Table.from_pylist(
        [
            {
                "packed_id": 9_000_500_000 + (i // 3),
                "slot": f"c{i % 3 + 1}",
                "comment_id": c,
            }
            for i, c in enumerate(cids)
        ],
        schema=packed.PACKED_MAP,
    )
    single_ledger = write_ledger(
        tmp_path / "single.jsonl",
        [ledger_row(c, "screen@1", 100) for c in cids],
    )
    packed_ledger = write_ledger(
        tmp_path / "packed.jsonl",
        [
            ledger_row(9_000_500_000 + i, "packed-screen@1", 120)
            for i in range(2)
        ],
    )
    res = packed.compare_packed(
        single,
        unpacked,
        single_ledger=single_ledger,
        packed_ledger=packed_ledger,
        packed_map=pmap,
    )
    assert res["n"] == 6
    assert res["pearson"] == pytest.approx(
        float(np.corrcoef(single_noul, packed_noul)[0, 1])
    )
    assert res["agreement_at_0_5"] == 1.0
    assert res["mean_abs_diff"] == pytest.approx(0.15 / 6)
    assert res["tokens_per_comment"] == {"single": 100.0, "packed": 40.0}


def test_compare_packed_edge_cases(tmp_path):
    cids = [9_000_000_001, 9_000_000_002]
    single = answers_table(
        [(c, "firsthand_problem", 0.5) for c in cids]  # zero variance
    )
    unpacked = pa.Table.from_pylist(
        [
            {
                "comment_id": c,
                "question_id": "firsthand_problem",
                "noul": v,
            }
            for c, v in zip(cids, [0.6, 0.4])
        ],
        schema=packed.UNPACKED,
    )
    res = packed.compare_packed(single, unpacked)
    assert res["n"] == 2
    assert res["pearson"] is None
    assert res["agreement_at_0_5"] == 0.5
    assert res["mean_abs_diff"] == pytest.approx(0.1)
    assert res["tokens_per_comment"] == {"single": None, "packed": None}

    empty = answers_table([])
    res = packed.compare_packed(empty, unpacked)
    assert res["n"] == 0
    assert res["pearson"] is None
    assert res["agreement_at_0_5"] is None
    assert res["mean_abs_diff"] is None


def test_run_packed_dry_run(pilot_repo, monkeypatch, capsys):  # noqa: F811
    pilot_draw(SNAPSHOT_ID, n_target=80, min_per_stratum=10, seed=7)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    stages.run_screen(SAMPLE_ID, RUN_ID, yes=True)
    capsys.readouterr()
    n_screen = len(seen)
    out = packed.run_packed(RUN_ID, n=12, k=5, seed=1)
    assert out["dispatched"] is False
    assert len(seen) == n_screen
    printed = json.loads(capsys.readouterr().out)
    assert printed == out["estimate"]
    assert out["estimate"]["question_set"] == "packed-screen@1"
    assert out["estimate"]["calls"] == math.ceil(12 / 5)
    assert not paths.run_dir(PACKED_RUN).exists()


def test_run_packed_end_to_end(pilot_repo, monkeypatch, capsys):  # noqa: F811
    table = pilot_draw(SNAPSHOT_ID, n_target=80, min_per_stratum=10, seed=7)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    stages.run_screen(SAMPLE_ID, RUN_ID, yes=True)
    capsys.readouterr()
    n_screen = len(seen)

    out = packed.run_packed(RUN_ID, n=12, k=5, seed=1, yes=True)
    assert out["dispatched"] is True
    assert len(seen) - n_screen == 3  # ceil(12/5) packed calls
    assert out["estimate"]["calls"] == 3

    run_dir = paths.run_dir(PACKED_RUN)
    pmap = pq.read_table(run_dir / "packed_map.parquet")
    assert pmap.schema == packed.PACKED_MAP
    assert pmap.num_rows == 12
    sample_ids = sorted(int(c) for c in table.column("comment_id").to_pylist())
    expected_subset = sorted(
        int(c)
        for c in np.random.default_rng(1).choice(
            sample_ids, min(12, len(sample_ids)), replace=False
        )
    )
    assert sorted(pmap.column("comment_id").to_pylist()) == expected_subset

    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["budget"] == "pilot"
    assert [e["label"] for e in manifest["question_sets"]] == [
        "packed-screen@1"
    ]

    answers = pq.read_table(run_dir / "answers")
    assert {r["question_set"] for r in answers.to_pylist()} == {
        "packed-screen@1"
    }
    unpacked = packed.unpack_answers(answers, pmap)
    assert sorted(unpacked.column("comment_id").to_pylist()) == expected_subset

    # The mock's noul is text-driven, so packed answers equal single answers.
    single_answers = pq.read_table(paths.run_dir(RUN_ID) / "answers")
    res = packed.compare_packed(
        single_answers,
        unpacked,
        single_ledger=paths.ledger_path(RUN_ID),
        packed_ledger=paths.ledger_path(PACKED_RUN),
        packed_map=pmap,
    )
    assert res["n"] == 12
    assert res["mean_abs_diff"] == 0.0
    assert res["agreement_at_0_5"] == 1.0
    assert res["pearson"] is None or res["pearson"] == pytest.approx(1.0)
    assert res["tokens_per_comment"]["single"] > 0
    assert res["tokens_per_comment"]["packed"] > 0

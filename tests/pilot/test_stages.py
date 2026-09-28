"""Task 7.2: screen and facet stages — dry-run estimate, --yes dispatch, and
the gate + seeded-random facet selection."""

import json

import numpy as np
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.evaluation.queue import read_answers
from atlas.pilot import stages
from atlas.pilot.draw import pilot_draw
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)

SAMPLE_ID = "pilot-7"
RUN_ID = "pilot-7"


def _draw():
    return pilot_draw(SNAPSHOT_ID, n_target=80, min_per_stratum=10, seed=7)


def _screen_yes(monkeypatch, seen):
    mock_env(monkeypatch, make_transport(seen=seen))
    return stages.run_screen(SAMPLE_ID, RUN_ID, yes=True)


def test_screen_dry_run_prints_estimate_and_writes_nothing(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    table = _draw()
    from atlas.inference import keys

    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(stages, "_transport", lambda: pytest.fail("transport"))
    out = stages.run_screen(SAMPLE_ID, RUN_ID)
    assert out["dispatched"] is False
    printed = json.loads(capsys.readouterr().out)
    assert printed == out["estimate"]
    est = out["estimate"]
    assert est["question_set"] == "screen@1"
    assert est["calls"] == table.num_rows
    assert est["input_tokens"] > 0 and est["usd"] > 0
    assert est["budget"] == "pilot" and est["cap_usd"] == 0.50
    assert not paths.run_dir(RUN_ID).exists()


def test_screen_yes_dispatches_every_sampled_comment(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    table = _draw()
    seen = []
    out = _screen_yes(monkeypatch, seen)
    assert out["dispatched"] is True
    assert out["run"]["completed"] == table.num_rows
    assert out["run"]["failed"] == 0
    assert len(seen) == table.num_rows
    printed = json.loads(capsys.readouterr().out)
    assert printed == out["estimate"]

    run_dir = paths.run_dir(RUN_ID)
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["budget"] == "pilot"
    assert manifest["model"] == stages.MODEL
    assert [e["label"] for e in manifest["question_sets"]] == ["screen@1"]
    pilot_meta = json.loads((run_dir / "pilot.json").read_text())
    assert pilot_meta == {
        "run_id": RUN_ID,
        "sample_id": SAMPLE_ID,
        "snapshot_id": SNAPSHOT_ID,
    }

    rows = pq.read_table(run_dir / "answers").to_pylist()
    assert {r["question_set"] for r in rows} == {"screen@1"}
    assert {r["question_id"] for r in rows} == {
        "firsthand_problem",
        "account_type",
    }
    sampled = {int(c) for c in table.column("comment_id").to_pylist()}
    answers = read_answers(RUN_ID, "firsthand_problem")
    assert set(answers) == sampled

    # noul follows the transport's PAIN rule against the real comment text.
    from atlas.sources.items import load_items

    items = load_items(paths.snapshot_dir(SNAPSHOT_ID), sorted(sampled))
    for item in items:
        want = 0.9 if "PAIN" in item["comment"] else 0.1
        assert answers[item["comment_id"]]["noul"] == pytest.approx(want)


def test_unknown_budget_exits(pilot_repo):  # noqa: F811
    _draw()
    with pytest.raises(SystemExit):
        stages.run_screen(SAMPLE_ID, RUN_ID, budget="nope")


def _gate_and_rest():
    scores = {
        c: a["noul"]
        for c, a in read_answers(RUN_ID, "firsthand_problem").items()
        if a["noul"] is not None
    }
    gate = sorted(c for c in scores if scores[c] >= 0.3)
    rest = sorted(c for c in scores if scores[c] < 0.3)
    return scores, gate, rest


def test_facets_dry_run_makes_no_requests(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _draw()
    seen = []
    _screen_yes(monkeypatch, seen)
    capsys.readouterr()
    n_screen = len(seen)
    out = stages.run_facets(RUN_ID)
    assert out["dispatched"] is False
    assert len(seen) == n_screen
    assert out["estimate"]["question_set"] == "facets@1"
    printed = json.loads(capsys.readouterr().out)
    assert printed == out["estimate"]
    assert not (paths.run_dir(RUN_ID) / "facet_selection.parquet").exists()


def test_facets_gate_plus_seeded_random(pilot_repo, monkeypatch, capsys):  # noqa: F811
    table = _draw()
    seen = []
    _screen_yes(monkeypatch, seen)
    capsys.readouterr()
    scores, gate, rest = _gate_and_rest()
    assert gate and rest  # fixture gives both sides of the 0.3 gate
    k = round(0.10 * len(rest))
    expected_random = sorted(
        int(c) for c in np.random.default_rng(1).choice(rest, k, replace=False)
    )

    out = stages.run_facets(RUN_ID, yes=True)
    assert out["dispatched"] is True
    run_dir = paths.run_dir(RUN_ID)
    sel = pq.read_table(run_dir / "facet_selection.parquet").to_pylist()
    by_rule = {"gate": set(), "random": set()}
    for r in sel:
        by_rule[r["rule"]].add(r["comment_id"])
        assert r["screen_p"] == pytest.approx(scores[r["comment_id"]])
        assert r["selection_prob"] == pytest.approx(
            1.0 if r["rule"] == "gate" else k / len(rest)
        )
    assert by_rule["gate"] == set(gate)
    assert by_rule["random"] == set(expected_random)
    assert len(seen) == table.num_rows + len(sel)

    facet_ids = {
        r["comment_id"]
        for r in pq.read_table(run_dir / "answers").to_pylist()
        if r["question_set"] == "facets@1"
    }
    assert facet_ids == set(gate) | set(expected_random)
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["budget"] == "pilot"
    assert [e["label"] for e in manifest["question_sets"]] == [
        "screen@1",
        "facets@1",
    ]


def test_facets_same_seed_reproduces_selection(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _draw()
    seen = []
    _screen_yes(monkeypatch, seen)
    capsys.readouterr()
    stages.run_facets(RUN_ID, yes=True)
    capsys.readouterr()
    run_dir = paths.run_dir(RUN_ID)
    first = pq.read_table(run_dir / "facet_selection.parquet").to_pylist()
    n_requests = len(seen)
    out = stages.run_facets(RUN_ID, yes=True)
    # The done set short-circuits: no new requests, identical selection file.
    assert len(seen) == n_requests
    assert out["run"]["skipped_completed"] == len(first)
    again = pq.read_table(run_dir / "facet_selection.parquet").to_pylist()
    assert again == first

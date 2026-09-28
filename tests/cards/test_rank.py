"""Transparent weighted ranking of need cards (and explore/confirm split)."""

import json
from pathlib import Path

import pyarrow as pa
import pytest

from atlas import paths
from atlas.cards.rank import (
    evaluate_criteria,
    load_criteria,
    load_weights,
    rank_cards,
    ranking_inputs,
    split_by_half,
)

REPO = Path(__file__).resolve().parents[2]


def metrics_table(rows):
    keys = list(rows[0])
    return pa.table(
        {k: [r.get(k) for r in rows] for k in keys}
    )


def test_order_follows_single_weight_and_norms():
    metrics = metrics_table(
        [
            {"card_id": "c0001", "n_authors": 5, "n_threads": 1},
            {"card_id": "c0002", "n_authors": 10, "n_threads": 3},
            {"card_id": "c0003", "n_authors": 3, "n_threads": 2},
        ]
    )
    weights = {"n_authors": 1.0, "n_threads": 0.0}
    r = rank_cards(metrics, weights)
    assert r.column_names == [
        "card_id",
        "n_authors_norm",
        "n_threads_norm",
        "score",
        "rank",
        "weights_json",
    ]
    assert r["card_id"].to_pylist() == ["c0002", "c0001", "c0003"]
    assert r["rank"].to_pylist() == [1, 2, 3]
    norm = r["n_authors_norm"].to_pylist()
    assert min(norm) == 0.0 and max(norm) == 1.0
    assert all(0.0 <= v <= 1.0 for v in norm)
    assert all(
        v == json.dumps(weights, sort_keys=True)
        for v in r["weights_json"].to_pylist()
    )


def test_ties_break_by_card_id():
    metrics = metrics_table(
        [
            {"card_id": "c0002", "n_authors": 5},
            {"card_id": "c0001", "n_authors": 5},
        ]
    )
    r = rank_cards(metrics, {"n_authors": 1.0})
    assert r["card_id"].to_pylist() == ["c0001", "c0002"]


def test_missing_weighted_column_raises():
    metrics = metrics_table([{"card_id": "c0001", "n_authors": 5}])
    with pytest.raises(ValueError, match="nope"):
        rank_cards(metrics, {"nope": 1.0})


def test_load_weights_and_order_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIGS", tmp_path)
    cfg = tmp_path / "ranking.toml"
    cfg.write_text("[weights]\nn_authors = 1.0\nn_threads = 0.0\n")
    assert load_weights() == {"n_authors": 1.0, "n_threads": 0.0}
    metrics = metrics_table(
        [
            {"card_id": "c0001", "n_authors": 5, "n_threads": 1},
            {"card_id": "c0002", "n_authors": 1, "n_threads": 9},
            {"card_id": "c0003", "n_authors": 9, "n_threads": 1},
        ]
    )
    r = rank_cards(metrics, load_weights())
    assert r["card_id"].to_pylist() == ["c0003", "c0001", "c0002"]
    cfg.write_text("[weights]\nn_authors = 0.0\nn_threads = 1.0\n")
    r2 = rank_cards(metrics, load_weights())
    assert r2["card_id"].to_pylist() == ["c0002", "c0001", "c0003"]


def test_ranking_inputs_derives_columns():
    metrics = metrics_table(
        [
            {
                "card_id": "c0001",
                "n_comments_capped": 7,
                "paid_rate": 0.5,
                "switched_rate": None,
                "abandoned_rate": 0.8,
            }
        ]
    )
    conv = pa.table(
        {
            "card_id": pa.array(["c0001"], type=pa.string()),
            "effective_domains": pa.array([2.0], type=pa.float64()),
            "effective_roles": pa.array([1.5], type=pa.float64()),
        }
    )
    out = ranking_inputs(metrics, conv)
    r = out.to_pylist()[0]
    assert r["n_authors_capped"] == 7
    assert r["commercial_rate"] == pytest.approx(0.8)
    assert r["effective_domains"] == 2.0
    assert r["effective_roles"] == 1.5
    out2 = ranking_inputs(metrics)
    assert "commercial_rate" in out2.column_names
    assert "effective_domains" not in out2.column_names


def test_shipped_ranking_toml_end_to_end():
    from atlas.cards.convergence import convergence
    from atlas.cards.metrics import card_metrics
    from tests.cards.test_metrics import fixture as metrics_fixture

    assignments, answers, comments, sample, replies = metrics_fixture()
    m = card_metrics(assignments, answers, comments, sample, replies=replies)
    conv = convergence(assignments, answers, comments)
    weights = load_weights(REPO / "configs" / "ranking.toml")
    assert weights["max_thread_share"] == -1.0
    r = rank_cards(ranking_inputs(m, conv), weights)
    assert r.num_rows == 2
    assert r["rank"].to_pylist() == [1, 2]
    for key in weights:
        assert f"{key}_norm" in r.column_names
        assert all(0.0 <= v <= 1.0 for v in r[f"{key}_norm"].to_pylist())


# ---- Task 13.4: explore/confirm split and pre-registered criteria ----

STORY_EXPLORE = 9_000_000_000  # contracts.half_of -> "explore"
STORY_CONFIRM = 9_000_000_001  # contracts.half_of -> "confirm"
CRITERIA = {
    "min_authors": 10,
    "min_periods": 3,
    "min_domains": 2,
    "max_thread_share": 0.30,
}


def half_metrics_table(rows):
    defaults = {
        "n_authors": 12,
        "n_periods": 4,
        "n_domains": 3,
        "max_thread_share": 0.2,
    }
    return pa.Table.from_pylist(
        [{**defaults, **r} for r in rows],
        schema=pa.schema(
            [
                ("card_id", pa.string()),
                ("n_authors", pa.int64()),
                ("n_periods", pa.int64()),
                ("n_domains", pa.int64()),
                ("max_thread_share", pa.float64()),
            ]
        ),
    )


def test_split_by_half():
    t = pa.table(
        {
            "comment_id": pa.array([1, 2, 3], type=pa.int64()),
            "story_id": pa.array(
                [STORY_EXPLORE, STORY_CONFIRM, None], type=pa.int64()
            ),
        }
    )
    halves = split_by_half(t)
    assert set(halves) == {"explore", "confirm"}
    assert halves["explore"]["comment_id"].to_pylist() == [1]
    assert halves["confirm"]["comment_id"].to_pylist() == [2]


def test_criteria_candidate_and_failures():
    explore = half_metrics_table(
        [{"card_id": "c0001"}, {"card_id": "c0002"}, {"card_id": "c0003"}]
    )
    confirm = half_metrics_table(
        [
            {"card_id": "c0001"},
            {"card_id": "c0002", "n_authors": 7},
            {"card_id": "c0004"},
        ]
    )
    out = evaluate_criteria(explore, confirm, CRITERIA)
    rows = {r["card_id"]: r for r in out.to_pylist()}
    assert rows["c0001"] == {
        "card_id": "c0001",
        "passes_explore": True,
        "passes_confirm": True,
        "candidate": True,
        "reasons": [],
    }
    assert rows["c0002"]["passes_explore"] is True
    assert rows["c0002"]["passes_confirm"] is False
    assert rows["c0002"]["candidate"] is False
    assert rows["c0002"]["reasons"] == ["confirm: n_authors 7 < 10"]
    # c0003 absent from confirm; c0004 absent from explore
    assert rows["c0003"]["reasons"] == ["confirm: missing"]
    assert rows["c0004"]["reasons"] == ["explore: missing"]
    assert out["card_id"].to_pylist() == ["c0001", "c0002", "c0003", "c0004"]


def test_criteria_boundary_and_null():
    ok = half_metrics_table([{"card_id": "c0001", "max_thread_share": 0.30}])
    out = evaluate_criteria(ok, ok, CRITERIA)
    assert out["candidate"].to_pylist() == [True]
    null_domains = half_metrics_table(
        [{"card_id": "c0001", "n_domains": None}]
    )
    out2 = evaluate_criteria(null_domains, ok, CRITERIA)
    row = out2.to_pylist()[0]
    assert row["candidate"] is False
    assert "explore: n_domains is null" in row["reasons"]


def test_load_criteria_shipped_file():
    criteria = load_criteria(REPO / "configs" / "finding_criteria.toml")
    assert criteria == {
        "min_authors": 10,
        "min_periods": 3,
        "min_domains": 2,
        "max_thread_share": 0.30,
    }

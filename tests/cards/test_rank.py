"""Transparent weighted ranking of need cards (and explore/confirm split)."""

import json
from pathlib import Path

import pyarrow as pa
import pytest

from atlas import paths
from atlas.cards.rank import load_weights, rank_cards, ranking_inputs

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

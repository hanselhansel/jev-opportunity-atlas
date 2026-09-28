import numpy as np
import pytest

from atlas.evaluation.metrics import (
    _draw_counts,
    binary_metrics,
    choice_confusion,
    reliability_bins,
    threshold_for_recall,
    threshold_for_recall_lb,
)


def test_unweighted_precision_recall():
    m = binary_metrics(y_true=[1, 1, 0, 0, 1], y_score=[0.9, 0.2, 0.8, 0.1, 0.7], threshold=0.5,
                       n_boot=200, seed=0)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["precision_ci"][0] <= m["precision"] <= m["precision_ci"][1]


def test_weights_change_population_estimates():
    m = binary_metrics(y_true=[1, 0], y_score=[0.9, 0.9], threshold=0.5, weights=[1, 9], n_boot=50, seed=0)
    assert m["precision"] == pytest.approx(0.1)


def test_threshold_for_recall():
    t = threshold_for_recall(y_true=[1, 1, 1, 1, 0], y_score=[0.9, 0.6, 0.4, 0.2, 0.1], target=0.75)
    assert t == pytest.approx(0.4)


def test_reliability_bins_report_counts():
    bins = reliability_bins(y_true=[1, 0, 1, 1], y_score=[0.05, 0.15, 0.95, 0.85], n_bins=10)
    assert [b["n"] for b in bins if b["n"]] == [1, 1, 1, 1]
    assert all("observed" in b and "mean_predicted" in b for b in bins)


def test_reliability_bins_weighted_and_empty():
    bins = reliability_bins(y_true=[1, 0], y_score=[0.12, 0.18], n_bins=10, weights=[3, 1])
    assert bins[1]["n"] == 2 and bins[1]["observed"] == pytest.approx(0.75)
    assert bins[1]["mean_predicted"] == pytest.approx((0.36 + 0.18) / 4)
    assert bins[0]["n"] == 0 and bins[0]["observed"] is None and bins[0]["mean_predicted"] is None


def test_stratified_draws_keep_stratum_sizes():
    strata = np.array(["a"] * 3 + ["b"] * 7)
    _, counts, unit_strata = _draw_counts(strata, None, n_boot=100, seed=1)
    assert counts.shape == (100, 10)
    assert (counts[:, unit_strata == "a"].sum(axis=1) == 3).all()
    assert (counts[:, unit_strata == "b"].sum(axis=1) == 7).all()


def test_clusters_are_resampled_whole():
    clusters = np.array([1, 1, 2, 2, 3])
    unit_of_row, counts, _ = _draw_counts(None, clusters, n_boot=20, seed=0)
    assert counts.shape == (20, 3) and (counts.sum(axis=1) == 3).all()
    assert unit_of_row[0] == unit_of_row[1] and unit_of_row[2] == unit_of_row[3]


def test_undefined_replicates_are_counted():
    m = binary_metrics(y_true=[0, 0, 0], y_score=[0.9, 0.1, 0.2], threshold=0.5, n_boot=30, seed=0)
    assert m["recall"] is None and m["n_undefined"] == 30
    assert m["recall_ci"] == [None, None] and m["precision"] == pytest.approx(0.0)


def test_threshold_lower_bound_is_conservative():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 200)
    score = np.clip(y * 0.4 + rng.random(200) * 0.6, 0, 1)
    point = threshold_for_recall(y, score, target=0.9)
    res = threshold_for_recall_lb(y, score, target=0.9, strata=None, n_boot=300, seed=0)
    assert res["threshold"] <= point
    assert res["recall_lower_bound"] >= 0.9 and res["point_recall"] >= res["recall_lower_bound"]


def test_choice_confusion():
    c = choice_confusion(["a", "a", "b"], ["a", "b", "b"])
    assert c["n"] == 3 and c["accuracy"] == pytest.approx(2 / 3)
    assert c["matrix"]["a"]["b"] == 1 and c["matrix"]["b"]["b"] == 1

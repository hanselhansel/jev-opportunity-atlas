import numpy as np
import pytest

from atlas.estimation.robust import (
    author_capped_weights,
    benjamini_hochberg,
    bootstrap_pvalue,
    drop_top_share,
    leave_one_cluster_out,
)


def test_leave_one_cluster_out_heaviest_cluster_dominates():
    values = np.array([5, 5, 1, 1, 1, 1], dtype=float)
    clusters = np.array([1, 1, 2, 3, 4, 5])
    out = leave_one_cluster_out(values, clusters, stat_fn=np.sum, k=2)
    assert out["full"] == 14
    assert out["min"] == 4
    assert out["max"] == 13
    assert out["max_cluster_share"] == pytest.approx(10 / 14)
    assert out["flag"] is True
    assert out["dropped"] == [1, 2]


def test_leave_one_cluster_out_balanced_clusters_not_flagged():
    values = np.ones(20)
    clusters = np.arange(20)
    out = leave_one_cluster_out(values, clusters, stat_fn=np.mean, k=3)
    assert out["full"] == pytest.approx(1.0)
    assert out["min"] == pytest.approx(1.0)
    assert out["max"] == pytest.approx(1.0)
    assert out["max_cluster_share"] == pytest.approx(0.05)
    assert out["flag"] is False
    assert len(out["dropped"]) == 3


def test_drop_top_share_removes_largest_clusters():
    clusters = np.arange(200)
    values = np.ones(200)
    values[198] = 40.0
    values[199] = 50.0
    out = drop_top_share(values, clusters, share=0.01, stat_fn=np.mean)
    assert out["full"] == pytest.approx((198 + 40 + 50) / 200)
    assert out["n_dropped"] == 2
    assert out["dropped"] == [199, 198]
    assert out["estimate"] == pytest.approx(1.0)


def test_drop_top_share_raises_when_it_would_remove_everything():
    values = np.array([1.0, 2.0])
    clusters = np.array([7, 7])
    with pytest.raises(ValueError):
        drop_top_share(values, clusters, share=0.01)


def test_author_capped_weights_cap_per_author_contribution():
    authors = ["a"] * 6 + ["b"] * 2 + ["c"]
    w = author_capped_weights(authors, k=3)
    np.testing.assert_allclose(w, [0.5] * 6 + [1.0, 1.0, 1.0])
    assert w.sum() == pytest.approx(6.0)


def test_author_capped_weights_requires_k_at_least_one():
    with pytest.raises(ValueError):
        author_capped_weights(["a", "b"], k=0)


def test_benjamini_hochberg_hand_example():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205])
    rej = benjamini_hochberg(p, q=0.05)
    assert rej.dtype == bool
    assert rej.tolist() == [True, True, False, False, False, False, False, False]


def test_benjamini_hochberg_reports_rejections_in_input_order():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205])
    order = np.array([3, 0, 7, 1, 5, 2, 6, 4])
    shuffled = p[order]
    rej = benjamini_hochberg(shuffled, q=0.05)
    expected = np.isin(shuffled, p[:2])
    assert rej.tolist() == expected.tolist()


def test_benjamini_hochberg_empty_input():
    rej = benjamini_hochberg(np.array([]), q=0.05)
    assert rej.dtype == bool
    assert rej.size == 0


def test_benjamini_hochberg_rejects_pvalues_out_of_range():
    with pytest.raises(ValueError):
        benjamini_hochberg(np.array([-0.1, 0.5]))
    with pytest.raises(ValueError):
        benjamini_hochberg(np.array([0.5, 1.2]))


def test_bootstrap_pvalue_shifted_distribution_is_significant():
    rng = np.random.default_rng(0)
    reps = rng.normal(3.0, 1.0, 2000)
    assert bootstrap_pvalue(reps, null=0.0) < 0.01


def test_bootstrap_pvalue_centered_distribution_is_not_significant():
    rng = np.random.default_rng(1)
    reps = rng.normal(0.0, 1.0, 2000)
    assert bootstrap_pvalue(reps, null=0.0) > 0.2


def test_bootstrap_pvalue_hand_case():
    reps = np.array([-1.0, 1.0, 2.0, 3.0])
    assert bootstrap_pvalue(reps, null=0.0) == pytest.approx(0.8)

import numpy as np
import pytest

from atlas.sampling.estimate import weighted_proportion


def test_point_estimate_uses_weights():
    est = weighted_proportion(
        y=[1, 0, 1, 0],
        w=[1, 1, 3, 3],
        strata=["A", "A", "B", "B"],
        clusters=[1, 2, 3, 4],
        n_boot=200,
        seed=0,
    )
    assert est["estimate"] == pytest.approx(0.5)
    assert est["n"] == 4 and est["weighted_n"] == pytest.approx(8)
    assert est["hits"] == 2 and est["n_clusters"] == 4
    assert est["method"] == "stratified cluster bootstrap, percentile"
    assert est["too_few"] is True


def test_clustered_interval_is_wider_than_naive_when_threads_are_homogeneous():
    rng = np.random.default_rng(0)
    clusters = np.repeat(np.arange(40), 10)
    y = np.repeat(rng.integers(0, 2, 40), 10)  # whole threads agree
    kwargs = {"y": y, "w": np.ones(400), "strata": ["A"] * 400, "n_boot": 500, "seed": 1}
    clustered = weighted_proportion(clusters=clusters, **kwargs)
    naive = weighted_proportion(clusters=np.arange(400), **kwargs)

    def width(e):
        return e["ci_high"] - e["ci_low"]
    assert width(clustered) > 2 * width(naive)


def test_small_counts_are_flagged():
    est = weighted_proportion(
        y=[1] * 5 + [0] * 5,
        w=[1] * 10,
        strata=["A"] * 10,
        clusters=list(range(10)),
        n_boot=100,
        seed=0,
        min_hits=30,
    )
    assert est["too_few"] is True


def test_census_interval_is_zero():
    est = weighted_proportion(
        y=[1, 0, 1, 1],
        w=[1, 1, 1, 1],
        strata=["A"] * 4,
        clusters=[1, 2, 3, 4],
        fpc=[1.0] * 4,
        n_boot=100,
        seed=0,
    )
    assert est["ci_low"] == est["ci_high"] == est["estimate"] == 0.75


def test_domain_mask_keeps_full_design():
    est = weighted_proportion(
        y=[1, 0, 1, 0],
        w=[1, 1, 1, 1],
        strata=["A", "A", "B", "B"],
        clusters=[1, 2, 3, 4],
        domain=[True, True, False, False],
        n_boot=200,
        seed=0,
    )
    assert est["estimate"] == pytest.approx(0.5)
    assert est["n"] == 2


def test_single_cluster_strata_are_counted_and_fpc_validated():
    est = weighted_proportion(
        y=[1, 0, 1, 0, 1, 0],
        w=[1] * 6,
        strata=["A", "A", "A", "A", "B", "B"],
        clusters=[1, 2, 3, 4, 5, 5],
        n_boot=100,
        seed=0,
    )
    assert est["single_cluster_strata"] == 1
    assert est["n_clusters"] == 5
    with pytest.raises(ValueError):
        weighted_proportion(
            y=[1, 0],
            w=[1, 1],
            strata=["A", "A"],
            clusters=[1, 2],
            fpc=[0.1, 0.2],
            n_boot=10,
            seed=0,
        )

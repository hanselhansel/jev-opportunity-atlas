import inspect

import numpy as np
import pytest

from atlas.estimation.ppi import ppi_difference, ppi_mean, ppi_ratio


def simulate(rng, n_all=20_000, n_gold=600, prevalence=0.2, bias=0.1):
    y_all = rng.random(n_all) < prevalence
    # a biased predictor: over-predicts positives
    yhat_all = np.clip(y_all * 0.8 + bias + rng.normal(0, 0.1, n_all), 0, 1)
    gold = rng.choice(n_all, n_gold, replace=False)
    return y_all, yhat_all, gold


def test_point_estimate_corrects_bias():
    rng = np.random.default_rng(0)
    y, yhat, gold = simulate(rng)
    est = ppi_mean(yhat_all=yhat, y_gold=y[gold].astype(float), yhat_gold=yhat[gold],
                   n_boot=200, seed=0)
    naive = yhat.mean()
    assert abs(est["estimate"] - y.mean()) < abs(naive - y.mean())
    assert est["ci_low"] < y.mean() < est["ci_high"]
    assert 0.0 <= est["lambda"] <= 1.0


def test_coverage_in_repeated_simulation():
    covered = 0
    for s in range(60):
        rng = np.random.default_rng(100 + s)
        y, yhat, gold = simulate(rng, n_all=5_000, n_gold=300)
        est = ppi_mean(yhat_all=yhat, y_gold=y[gold].astype(float), yhat_gold=yhat[gold],
                       n_boot=150, seed=s)
        covered += est["ci_low"] <= y.mean() <= est["ci_high"]
    assert covered >= 51  # at least 85% of 60 nominal-95% intervals cover


def test_interval_not_wider_than_gold_only():
    rng = np.random.default_rng(3)
    y, yhat, gold = simulate(rng)
    ppi = ppi_mean(yhat_all=yhat, y_gold=y[gold].astype(float), yhat_gold=yhat[gold], n_boot=300, seed=1)
    only = ppi_mean(yhat_all=yhat, y_gold=y[gold].astype(float), yhat_gold=yhat[gold], n_boot=300, seed=1,
                    lam=0.0)
    assert ppi["ci_high"] - ppi["ci_low"] <= (only["ci_high"] - only["ci_low"]) * 1.05


def test_matches_ppi_py_on_simple_case():
    from ppi_py import ppi_mean_pointestimate
    rng = np.random.default_rng(5)
    y, yhat, gold = simulate(rng)
    ours = ppi_mean(yhat_all=yhat, y_gold=y[gold].astype(float), yhat_gold=yhat[gold], n_boot=50, seed=0,
                    lam=1.0)["estimate"]
    theirs = float(np.asarray(ppi_mean_pointestimate(y[gold].astype(float), yhat[gold], yhat, lam=1.0)).ravel()[0])
    assert ours == pytest.approx(theirs, abs=0.01)


def test_weights_and_clusters_are_used():
    rng = np.random.default_rng(7)
    n_threads = 400
    threads = rng.integers(0, n_threads, 8_000)
    thread_effect = rng.normal(0, 0.15, n_threads)
    p = np.clip(0.2 + thread_effect[threads], 0.01, 0.99)
    y = (rng.random(threads.size) < p).astype(float)
    yhat = np.clip(0.8 * y + 0.1 + rng.normal(0, 0.1, y.size), 0, 1)
    strata = threads % 2
    w = np.where(strata == 0, 1.0, 3.0)
    sel = np.where(yhat > 0.5, 0.2, 0.05)
    gold = np.flatnonzero(rng.random(y.size) < sel)
    est = ppi_mean(yhat_all=yhat, y_gold=y[gold], yhat_gold=yhat[gold], w_all=w, w_gold=w[gold],
                   sel_prob_gold=sel[gold], strata_all=strata, strata_gold=strata[gold],
                   clusters_all=threads, clusters_gold=threads[gold], n_boot=300, seed=0)
    truth = np.sum(w * y) / np.sum(w)
    assert est["ci_low"] < truth < est["ci_high"]
    assert est["n_all"] == y.size and est["n_gold"] == gold.size
    assert est["method"] == "PPI++ with stratified cluster bootstrap"
    naive = ppi_mean(yhat_all=yhat, y_gold=y[gold], yhat_gold=yhat[gold], n_boot=300, seed=0)
    assert abs(est["estimate"] - truth) < abs(naive["estimate"] - truth)


def test_rejects_bad_selection_probability():
    with pytest.raises(ValueError):
        ppi_mean(yhat_all=np.ones(5), y_gold=np.ones(2), yhat_gold=np.ones(2),
                 sel_prob_gold=np.array([0.5, 0.0]), n_boot=10)


def noisy(rng, y, fp=0.15, fn=0.2):
    """Predicted probability with false positives and misses."""
    flip_up = rng.random(y.size) < fp
    flip_down = rng.random(y.size) < fn
    hard = np.where(y, ~flip_down, flip_up)
    return np.clip(hard * 0.7 + 0.15 + rng.normal(0, 0.05, y.size), 0, 1)


def test_ratio_uses_two_corrected_means():
    rng = np.random.default_rng(11)
    n = 20_000
    firsthand = rng.random(n) < 0.3
    billing = firsthand & (rng.random(n) < 0.25)
    f_hat = noisy(rng, firsthand)
    b_hat = noisy(rng, billing, fp=0.1, fn=0.3)
    gold = rng.choice(n, 800, replace=False)
    num = (b_hat, billing[gold].astype(float), b_hat[gold])
    den = (f_hat, firsthand[gold].astype(float), f_hat[gold])
    est = ppi_ratio(num, den, n_boot=300, seed=0)
    truth = billing.mean() / firsthand.mean()
    naive = b_hat.mean() / f_hat.mean()
    assert abs(est["estimate"] - truth) < abs(naive - truth)
    assert est["ci_low"] < truth < est["ci_high"]
    assert abs(est["naive_model_estimate"] - naive) < 1e-9
    assert len(est["lambda"]) == 2


def test_never_conditions_on_predictions():
    params = set(inspect.signature(ppi_ratio).parameters)
    assert not {p for p in params if "mask" in p or "pred" in p or "filter" in p}


def test_ratio_with_clusters_and_strata():
    rng = np.random.default_rng(12)
    threads = rng.integers(0, 500, 10_000)
    strata = threads % 3
    firsthand = rng.random(threads.size) < 0.3
    billing = firsthand & (rng.random(threads.size) < 0.4)
    f_hat, b_hat = noisy(rng, firsthand), noisy(rng, billing)
    gold = rng.choice(threads.size, 600, replace=False)
    kw = {"strata_all": strata, "strata_gold": strata[gold], "clusters_all": threads,
          "clusters_gold": threads[gold], "n_boot": 200, "seed": 1}
    est = ppi_ratio((b_hat, billing[gold] * 1.0, b_hat[gold]),
                    (f_hat, firsthand[gold] * 1.0, f_hat[gold]), **kw)
    assert est["ci_low"] < billing.mean() / firsthand.mean() < est["ci_high"]


def half_year(rng, p1, p2, n=12_000, n_gold=900, fp=0.15, fn=0.2):
    group = np.where(np.arange(n) < n // 2, "H1", "H2")
    p = np.where(group == "H1", p1, p2)
    y = rng.random(n) < p
    yhat = noisy(rng, y, fp=fp, fn=fn)
    gold = rng.choice(n, n_gold, replace=False)
    return group, y, yhat, gold


def test_half_year_difference():
    rng = np.random.default_rng(21)
    group, y, yhat, gold = half_year(rng, 0.10, 0.15, n=20_000, n_gold=2_000, fp=0.05, fn=0.1)
    est = ppi_difference(yhat, y[gold].astype(float), yhat[gold], group, group[gold],
                         n_boot=300, seed=0)
    assert est["groups"] == ("H1", "H2")
    assert abs(est["estimate"] - 0.05) < 0.02
    assert est["ci_low"] > 0
    assert abs(est["estimate"] - (est["estimate_b"] - est["estimate_a"])) < 1e-12


def test_half_year_null_interval_covers_zero():
    covered = 0
    for s in range(40):
        rng = np.random.default_rng(300 + s)
        group, y, yhat, gold = half_year(rng, 0.10, 0.10, n=4_000, n_gold=400)
        est = ppi_difference(yhat, y[gold].astype(float), yhat[gold], group, group[gold],
                             n_boot=150, seed=s)
        covered += est["ci_low"] <= 0 <= est["ci_high"]
    assert covered >= 34  # at least 85% of 40

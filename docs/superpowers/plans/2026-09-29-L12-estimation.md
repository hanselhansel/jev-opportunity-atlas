# L12: Prediction-powered estimates with thread clustering

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l12-estimation

**Goal:** Every published proportion, ratio, and half-year change is estimated by combining Jev's answers on the whole sample with Hansel's gold labels, via prediction-powered inference (PPI++), with design weights, thread-clustered intervals, robustness checks, and multiple-comparison control.

**Architecture:** New package `src/atlas/estimation/`. Pure numpy functions, plus a thin cross-check against `ppi_py` (already installed). Inputs are arrays: Jev score `yhat` for every sampled comment, human label `y` for gold items, breadth design weights, gold selection probabilities (contract `GOLD_DRAWS.selection_prob`), strata, and thread IDs.

**Background (read):**
- Angelopoulos et al., "Prediction-Powered Inference" (Science 2023)
- PPI++ (arXiv 2311.01453)
- Stratified PPI (arXiv 2406.04291)
- PPI with nonuniform sampling (arXiv 2501.18577)
- `docs/superpowers/specs/2026-09-29-analysis-design.md` section 4, step 9

**Estimator.** For a mean of true labels:

- `mean_hat_all = Σ w_i yhat_i / Σ w_i` over all sampled comments, where `w` is the breadth design weight.
- `rectifier = Σ v_j (y_j - λ yhat_j) / Σ v_j` over gold items, where `v_j = w_j / selection_prob_j`.
- `θ = λ · mean_hat_all + rectifier`.
- `λ` is the PPI++ power-tuning value, estimated from the data, clipped to [0, 1]. `λ = 0` gives the gold-only estimator.

Intervals come from a stratified cluster bootstrap that resamples threads within breadth strata, independently for the unlabeled and gold parts, recomputing `λ` in each replicate.

**Files you own:**
- `src/atlas/estimation/__init__.py`, `src/atlas/estimation/ppi.py`, `src/atlas/estimation/robust.py`
- `src/atlas/estimation/cli.py` is NOT allowed (registry is frozen); expose functions only
- `tests/estimation/__init__.py` (create it; it is your lane's new test package), `tests/estimation/test_ppi.py`, `tests/estimation/test_robust.py`

---

### Task 12.1: PPI mean with design and gold weights

- [ ] **Step 1: Test**

```python
# tests/estimation/test_ppi.py
import numpy as np
import pytest

from atlas.estimation.ppi import ppi_mean


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
```

- [ ] **Step 2: Fail. Step 3: Implement** `ppi_mean(yhat_all, y_gold, yhat_gold, w_all=None, w_gold=None, sel_prob_gold=None, strata_all=None, strata_gold=None, clusters_all=None, clusters_gold=None, lam=None, n_boot=2000, seed=0, alpha=0.05) -> dict`. Keys: `estimate`, `ci_low`, `ci_high`, `lambda`, `naive_model_estimate`, `gold_only_estimate`, `n_all`, `n_gold`, `method` (`"PPI++ with stratified cluster bootstrap"`). The unlabeled `yhat_all` excludes nothing; gold items also appear in `yhat_all` when they were sampled (document this). Chunk bootstrap replicates to bound memory.
  - If the `ppi_py` function name differs in the installed version, look it up with `python -c "import ppi_py; print(dir(ppi_py))"` and adapt the cross-check import only.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 12.2: Ratios and domains

- [ ] **Step 1: Test** `test_ratio_uses_two_corrected_means`: simulate `firsthand` (true and predicted) and `billing` (true and predicted) per comment; `ppi_ratio(num=(yhat_num_all, y_num_gold, yhat_num_gold), den=(...))` estimates `P(billing and firsthand) / P(firsthand)`. It must be closer to the truth than the naive ratio of predicted labels, with an interval covering the truth. Also `test_never_conditions_on_predictions`: the function signature takes no predicted-label mask.
- [ ] **Step 2: Fail. Step 3: Implement** `ppi_ratio(num, den, **same_kwargs)`: joint bootstrap (same resampled threads for numerator and denominator), ratio per replicate, percentile interval.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 12.3: Half-year change

- [ ] **Step 1: Test** `test_half_year_difference`: simulated shares 0.10 in H1 and 0.15 in H2; `ppi_difference(group_all, group_gold, ...)` returns an estimate near 0.05 whose interval excludes 0. In a null simulation (both 0.10), the interval includes 0 in at least 85% of 40 runs.
- [ ] **Step 2: Fail. Step 3: Implement** with a joint bootstrap over both halves.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 12.4: Robustness and multiple comparisons (`robust.py`)

- [ ] **Step 1: Tests**
  - `leave_one_cluster_out(values, clusters, stat_fn)` returns the min and max of the statistic when each of the top-k heaviest clusters is dropped, and `max_cluster_share` (flag when above 0.10).
  - `drop_top_share(values, clusters, share=0.01, stat_fn)` recomputes after removing the top 1% of clusters by contribution.
  - `author_capped_weights(authors, k=3)` returns weights so no author contributes more than k to a count.
  - `benjamini_hochberg(pvalues, q=0.05)` matches a hand-worked example: p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205] with q = 0.05 rejects the first 2.
  - `bootstrap_pvalue(reps, null=0.0)` gives a two-sided p-value from bootstrap replicates.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 12.5: Finish

- [ ] Module docstring in `ppi.py` explaining the estimator in plain words and citing the papers above.
- [ ] `scripts/verify.sh` must print `verify: ok` (keep simulation tests fast: the whole lane's tests under 60 seconds). Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

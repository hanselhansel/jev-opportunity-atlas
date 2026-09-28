"""Prediction-powered estimates of means, ratios, and half-year changes.

In plain words: Jev scores every sampled comment, which is cheap but biased. Hansel
labels a small gold subset, which is unbiased but noisy because it is small. The
estimator takes Jev's average over the whole sample, then adds a correction measured on
the gold items: how far the true labels sit from Jev's scores there. The correction
removes Jev's bias, and Jev's scores on the large sample shrink the noise.

For one mean:

- ``mean_hat_all = sum(w_i * yhat_i) / sum(w_i)`` over all sampled comments, where ``w``
  is the breadth design weight.
- ``rectifier = sum(v_j * (y_j - lam * yhat_j)) / sum(v_j)`` over gold items, where
  ``v_j = w_j / selection_prob_j`` (``GOLD_DRAWS.selection_prob``).
- ``theta = lam * mean_hat_all + rectifier``.

``lam`` is the PPI++ power-tuning value, ``cov(y, yhat) / ((1 + n_eff / N_eff) *
var(yhat))`` computed with the weights above (Kish effective sizes) and clipped to
[0, 1]. ``lam = 0`` is the gold-only estimator and ``lam = 1`` is plain PPI. Any fixed
``lam`` gives an unbiased estimate; tuning only changes the variance.

Gold items are a subsample of the sampled comments, so they also appear in
``yhat_all``. Nothing is excluded from the unlabeled part; this matches the nonuniform
sampling setting of Kluger et al.

Intervals come from a stratified cluster bootstrap: threads are resampled with
replacement within breadth strata, independently for the unlabeled part and the gold
part, and ``lam`` is recomputed in every replicate. The resampling unit is the pair
(stratum, thread); a thread that spans strata is resampled separately in each. The
interval is the percentile interval of the replicates. Ratios and differences use one
joint bootstrap, so numerator and denominator (or both halves) see the same resampled
threads. Ratios are always two corrected means; nothing conditions on Jev's predicted
labels.

References:

- Angelopoulos et al., "Prediction-Powered Inference," Science 2023 (arXiv 2301.09633)
- Angelopoulos, Duchi, Zrnic, "PPI++: Efficient Prediction-Powered Inference"
  (arXiv 2311.01453)
- Fisch et al., "Stratified Prediction-Powered Inference" (arXiv 2406.04291)
- Kluger et al., "Prediction-Powered Inference with Imputed Covariates and Nonuniform
  Sampling" (arXiv 2501.18577)
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

METHOD = "PPI++ with stratified cluster bootstrap"
_CHUNK_CELLS = 4_000_000  # bound on replicate-by-unit counts held in memory at once


def _vec(x, n: int, default: float, name: str) -> np.ndarray:
    if x is None:
        return np.full(n, default, dtype=float)
    arr = np.asarray(x, dtype=float).ravel()
    if arr.size != n:
        raise ValueError(f"{name} has length {arr.size}, expected {n}")
    return arr


def _labels(x, n: int, name: str, unique_default: bool) -> np.ndarray:
    if x is None:
        return np.arange(n) if unique_default else np.zeros(n, dtype=int)
    arr = np.asarray(x).ravel()
    if arr.size != n:
        raise ValueError(f"{name} has length {arr.size}, expected {n}")
    return arr


def _as_2d(x, name: str) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 1-D or 2-D")
    return arr


class _Part:
    """Per-unit sums for one part (unlabeled or gold), ready for resampling."""

    def __init__(self, strata, clusters, columns: np.ndarray):
        _, s_code = np.unique(strata, return_inverse=True)
        _, c_code = np.unique(clusters, return_inverse=True)
        pairs, inv = np.unique(np.stack([s_code, c_code], axis=1), axis=0, return_inverse=True)
        inv = inv.ravel()
        self.n_units = pairs.shape[0]
        self.unit_stratum = pairs[:, 0]
        self.sums = np.stack(
            [np.bincount(inv, weights=columns[:, j], minlength=self.n_units)
             for j in range(columns.shape[1])], axis=1)
        self.groups = [np.flatnonzero(self.unit_stratum == s) for s in np.unique(self.unit_stratum)]

    def point(self) -> np.ndarray:
        return self.sums.sum(axis=0)[None, :]

    def resample(self, rng: np.random.Generator, n_rep: int) -> np.ndarray:
        counts = np.zeros((n_rep, self.n_units))
        for idx in self.groups:
            m = idx.size
            counts[:, idx] = rng.multinomial(m, np.full(m, 1.0 / m), size=n_rep)
        return counts @ self.sums


def _all_columns(yhat: np.ndarray, w: np.ndarray, mask: np.ndarray) -> np.ndarray:
    wk = w[:, None] * mask
    return np.concatenate([wk, wk * yhat, wk * yhat**2, wk**2], axis=1)


def _gold_columns(y: np.ndarray, yhat: np.ndarray, v: np.ndarray, mask: np.ndarray) -> np.ndarray:
    vk = v[:, None] * mask
    return np.concatenate([vk, vk * y, vk * yhat, vk * y * yhat, vk**2], axis=1)


def _theta(a: np.ndarray, g: np.ndarray, k: int, lam: float | None):
    """Estimates and lambdas from summed moments. ``a`` and ``g`` are (reps, cols)."""
    a0, a1, a2, a3 = (a[:, i * k:(i + 1) * k] for i in range(4))
    g0, gy, gf, gyf, gvv = (g[:, i * k:(i + 1) * k] for i in range(5))
    with np.errstate(divide="ignore", invalid="ignore"):
        m_all = a1 / a0
        my, mf = gy / g0, gf / g0
        if lam is None:
            var_f = a2 / a0 - m_all**2
            cov = gyf / g0 - my * mf
            ratio_eff = (g0**2 / gvv) / (a0**2 / a3)
            lam_arr = cov / ((1.0 + ratio_eff) * var_f)
            lam_arr = np.where(np.isfinite(lam_arr) & (var_f > 1e-12), lam_arr, 0.0)
            lam_arr = np.clip(lam_arr, 0.0, 1.0)
        else:
            lam_arr = np.full_like(m_all, float(lam))
        theta = lam_arr * m_all + my - lam_arr * mf
    return theta, lam_arr, m_all, my


def _prepare(yhat_all, y_gold, yhat_gold, w_all=None, w_gold=None, sel_prob_gold=None,
             strata_all=None, strata_gold=None, clusters_all=None, clusters_gold=None,
             mask_all=None, mask_gold=None):
    yh_a, y_g, yh_g = _as_2d(yhat_all, "yhat_all"), _as_2d(y_gold, "y_gold"), _as_2d(yhat_gold, "yhat_gold")
    n_all, n_gold = yh_a.shape[0], y_g.shape[0]
    k = yh_a.shape[1]
    if y_g.shape != yh_g.shape or yh_g.shape[1] != k:
        raise ValueError("y_gold and yhat_gold must match yhat_all in columns and each other in shape")
    if n_all == 0 or n_gold == 0:
        raise ValueError("need at least one sampled comment and one gold item")
    w_a = _vec(w_all, n_all, 1.0, "w_all")
    w_g = _vec(w_gold, n_gold, 1.0, "w_gold")
    sel = _vec(sel_prob_gold, n_gold, 1.0, "sel_prob_gold")
    if np.any(~np.isfinite(sel)) or np.any(sel <= 0) or np.any(sel > 1):
        raise ValueError("sel_prob_gold must lie in (0, 1]")
    if np.any(w_a < 0) or np.any(w_g < 0):
        raise ValueError("weights must be non-negative")
    m_a = np.ones((n_all, k)) if mask_all is None else mask_all
    m_g = np.ones((n_gold, k)) if mask_gold is None else mask_gold
    part_all = _Part(_labels(strata_all, n_all, "strata_all", False),
                     _labels(clusters_all, n_all, "clusters_all", True), _all_columns(yh_a, w_a, m_a))
    part_gold = _Part(_labels(strata_gold, n_gold, "strata_gold", False),
                      _labels(clusters_gold, n_gold, "clusters_gold", True),
                      _gold_columns(y_g, yh_g, w_g / sel, m_g))
    return part_all, part_gold, k, n_all, n_gold


def _run(parts, k: int, lam, n_boot: int, seed: int, alpha: float,
         combine: Callable[[np.ndarray], np.ndarray]) -> dict:
    if n_boot < 1:
        raise ValueError("n_boot must be at least 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    part_all, part_gold = parts
    theta, lam_pt, m_all, my = _theta(part_all.point(), part_gold.point(), k, lam)
    rng = np.random.default_rng(seed)
    chunk = max(1, min(n_boot, _CHUNK_CELLS // max(part_all.n_units, part_gold.n_units, 1)))
    reps = []
    for start in range(0, n_boot, chunk):
        n_rep = min(chunk, n_boot - start)
        a = part_all.resample(rng, n_rep)
        g = part_gold.resample(rng, n_rep)
        reps.append(combine(_theta(a, g, k, lam)[0]))
    boot = np.concatenate(reps)
    finite = boot[np.isfinite(boot)]
    if finite.size == 0:
        ci_low = ci_high = float("nan")
    else:
        ci_low, ci_high = (float(q) for q in np.quantile(finite, [alpha / 2, 1 - alpha / 2]))
    return {
        "estimate": float(combine(theta)[0]),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "thetas": theta[0],
        "lambdas": lam_pt[0],
        "naive": m_all[0],
        "gold_only": my[0],
        "replicates": boot,
        "n_failed_replicates": int(boot.size - finite.size),
    }


def ppi_mean(yhat_all, y_gold, yhat_gold, w_all=None, w_gold=None, sel_prob_gold=None,
             strata_all=None, strata_gold=None, clusters_all=None, clusters_gold=None,
             lam=None, n_boot=2000, seed=0, alpha=0.05) -> dict:
    """PPI++ estimate of the mean of true labels, with a stratified cluster bootstrap CI.

    ``yhat_all`` holds Jev scores for every sampled comment (gold items included).
    ``y_gold``/``yhat_gold`` are Hansel's labels and Jev's scores on the gold items.
    ``w_*`` are breadth design weights, ``sel_prob_gold`` the gold selection
    probabilities, ``strata_*`` the breadth strata, and ``clusters_*`` thread IDs.
    Missing strata mean one stratum; missing clusters mean each item is its own thread.
    """
    parts = _prepare(yhat_all, y_gold, yhat_gold, w_all, w_gold, sel_prob_gold,
                     strata_all, strata_gold, clusters_all, clusters_gold)
    part_all, part_gold, k, n_all, n_gold = parts
    if k != 1:
        raise ValueError("ppi_mean takes one outcome; use ppi_ratio for two")
    res = _run((part_all, part_gold), k, lam, n_boot, seed, alpha, lambda t: t[:, 0])
    return {
        "estimate": res["estimate"],
        "ci_low": res["ci_low"],
        "ci_high": res["ci_high"],
        "lambda": float(res["lambdas"][0]),
        "naive_model_estimate": float(res["naive"][0]),
        "gold_only_estimate": float(res["gold_only"][0]),
        "n_all": n_all,
        "n_gold": n_gold,
        "method": METHOD,
        "replicates": res["replicates"],
        "n_failed_replicates": res["n_failed_replicates"],
    }


def _common(kwargs: dict) -> dict:
    allowed = {"w_all", "w_gold", "sel_prob_gold", "strata_all", "strata_gold",
               "clusters_all", "clusters_gold", "lam", "n_boot", "seed", "alpha"}
    extra = set(kwargs) - allowed
    if extra:
        raise TypeError(f"unexpected arguments: {sorted(extra)}")
    return {"lam": None, "n_boot": 2000, "seed": 0, "alpha": 0.05, **kwargs}


def _split(kw: dict):
    run_kw = {k: kw.pop(k) for k in ("lam", "n_boot", "seed", "alpha")}
    return kw, run_kw


def ppi_ratio(num, den, **kwargs) -> dict:
    """Ratio of two PPI++ means, e.g. P(billing and firsthand) / P(firsthand).

    ``num`` and ``den`` are each ``(yhat_all, y_gold, yhat_gold)`` for the joint event
    and the base event. Each part is corrected on its own; the ratio is taken per
    bootstrap replicate over the same resampled threads. Other keyword arguments are
    those of ``ppi_mean``.
    """
    prep_kw, run_kw = _split(_common(kwargs))
    stacked = [np.column_stack([np.asarray(a, dtype=float).ravel(), np.asarray(b, dtype=float).ravel()])
               for a, b in zip(num, den, strict=True)]
    part_all, part_gold, k, n_all, n_gold = _prepare(*stacked, **prep_kw)
    with np.errstate(divide="ignore", invalid="ignore"):
        res = _run((part_all, part_gold), k, combine=lambda t: t[:, 0] / t[:, 1], **run_kw)
        naive = float(res["naive"][0] / res["naive"][1])
        gold_only = float(res["gold_only"][0] / res["gold_only"][1])
    return {
        "estimate": res["estimate"],
        "ci_low": res["ci_low"],
        "ci_high": res["ci_high"],
        "numerator": float(res["thetas"][0]),
        "denominator": float(res["thetas"][1]),
        "lambda": [float(x) for x in res["lambdas"]],
        "naive_model_estimate": naive,
        "gold_only_estimate": gold_only,
        "n_all": n_all,
        "n_gold": n_gold,
        "method": METHOD,
        "replicates": res["replicates"],
        "n_failed_replicates": res["n_failed_replicates"],
    }


def ppi_difference(yhat_all, y_gold, yhat_gold, group_all, group_gold, groups=None,
                   **kwargs) -> dict:
    """Change in a PPI++ mean between two known groups, e.g. half-years H1 and H2.

    ``group_*`` give each item's group (known exactly, never predicted). ``groups`` is
    ``(a, b)``; the default is the two sorted distinct values of ``group_all``. The
    estimate is ``mean_b - mean_a``, from one joint bootstrap over both groups. Other
    keyword arguments are those of ``ppi_mean``.
    """
    prep_kw, run_kw = _split(_common(kwargs))
    g_all, g_gold = np.asarray(group_all).ravel(), np.asarray(group_gold).ravel()
    if groups is None:
        found = np.unique(g_all)
        if found.size != 2:
            raise ValueError(f"expected exactly two groups, found {found.size}")
        groups = (found[0].item(), found[1].item())
    a, b = groups
    yh_a = np.asarray(yhat_all, dtype=float).ravel()
    y_g, yh_g = np.asarray(y_gold, dtype=float).ravel(), np.asarray(yhat_gold, dtype=float).ravel()
    if g_all.size != yh_a.size or g_gold.size != y_g.size:
        raise ValueError("group arrays must match the item arrays in length")
    mask_all = np.column_stack([g_all == a, g_all == b]).astype(float)
    mask_gold = np.column_stack([g_gold == a, g_gold == b]).astype(float)
    part_all, part_gold, k, n_all, n_gold = _prepare(
        *(np.column_stack([x, x]) for x in (yh_a, y_g, yh_g)), mask_all=mask_all, mask_gold=mask_gold, **prep_kw)
    res = _run((part_all, part_gold), k, combine=lambda t: t[:, 1] - t[:, 0], **run_kw)
    return {
        "estimate": res["estimate"],
        "ci_low": res["ci_low"],
        "ci_high": res["ci_high"],
        "groups": (a, b),
        "estimate_a": float(res["thetas"][0]),
        "estimate_b": float(res["thetas"][1]),
        "lambda": [float(x) for x in res["lambdas"]],
        "naive_model_estimate": float(res["naive"][1] - res["naive"][0]),
        "gold_only_estimate": float(res["gold_only"][1] - res["gold_only"][0]),
        "n_all": n_all,
        "n_gold": n_gold,
        "method": METHOD,
        "replicates": res["replicates"],
        "n_failed_replicates": res["n_failed_replicates"],
    }

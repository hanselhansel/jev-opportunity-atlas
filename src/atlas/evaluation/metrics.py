"""Quality metrics over plain arrays: weighted precision, recall, F1 with stratified cluster
bootstrap intervals, recall-targeted thresholds, reliability bins, and choice confusion.

Callers drop `unsure` labels before calling. `y_true` is 0/1; a row is predicted positive
when `score >= threshold`. Undefined values (for example recall with no positives) are None.
"""

from __future__ import annotations

import math

import numpy as np


def _none(x: float) -> float | None:
    return None if x is None or math.isnan(x) else float(x)


def _weights(weights, n: int) -> np.ndarray:
    return np.ones(n) if weights is None else np.asarray(weights, dtype=float)


def _draw_counts(strata, clusters, n_boot: int, seed: int, n: int | None = None):
    """Stratified cluster bootstrap. A unit is a (stratum, cluster) pair; each replicate
    draws, within every stratum, as many units as the stratum has, with replacement.
    Returns (unit_of_row, counts[n_boot, n_units], unit_strata)."""
    if n is None:
        n = len(strata) if strata is not None else len(clusters)
    s = np.asarray(strata, dtype=object) if strata is not None else np.zeros(n, dtype=object)
    c = np.asarray(clusters, dtype=object) if clusters is not None else np.arange(n)
    keys = list(zip(s.tolist(), c.tolist()))
    index: dict = {}
    unit_of_row = np.array([index.setdefault(k, len(index)) for k in keys], dtype=int)
    unit_strata = np.array([k[0] for k in index], dtype=object)
    rng = np.random.default_rng(seed)
    counts = np.zeros((n_boot, len(index)), dtype=np.int64)
    for stratum in dict.fromkeys(unit_strata.tolist()):
        units = np.flatnonzero(unit_strata == stratum)
        draws = rng.integers(0, len(units), size=(n_boot, len(units)))
        for b in range(n_boot):
            counts[b] += np.bincount(units[draws[b]], minlength=len(index))
    return unit_of_row, counts, unit_strata


def _unit_sums(values: np.ndarray, unit_of_row: np.ndarray, n_units: int) -> np.ndarray:
    return np.bincount(unit_of_row, weights=values, minlength=n_units)


def _ratio(num, den):
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    out = np.full(np.broadcast(num, den).shape, np.nan)
    np.divide(num, den, out=out, where=den > 0)
    return out


def _ci(reps: np.ndarray, level: float = 0.95) -> list:
    if np.isnan(reps).all():
        return [None, None]
    lo, hi = np.nanpercentile(reps, [50 * (1 - level), 50 * (1 + level)])
    return [float(lo), float(hi)]


def binary_metrics(y_true, y_score, threshold: float, weights=None, clusters=None,
                   strata=None, n_boot: int = 2000, seed: int = 0) -> dict:
    t = np.asarray(y_true, dtype=int) == 1
    p = np.asarray(y_score, dtype=float) >= threshold
    w = _weights(weights, len(t))
    tp_w, fp_w, fn_w = (w * (t & p), w * (~t & p), w * (t & ~p))
    point_p = _ratio(tp_w.sum(), tp_w.sum() + fp_w.sum())
    point_r = _ratio(tp_w.sum(), tp_w.sum() + fn_w.sum())
    point_f = _ratio(2 * tp_w.sum(), 2 * tp_w.sum() + fp_w.sum() + fn_w.sum())

    unit_of_row, counts, _ = _draw_counts(strata, clusters, n_boot, seed, n=len(t))
    k = counts.shape[1]
    tp_b = counts @ _unit_sums(tp_w, unit_of_row, k)
    fp_b = counts @ _unit_sums(fp_w, unit_of_row, k)
    fn_b = counts @ _unit_sums(fn_w, unit_of_row, k)
    prec_b = _ratio(tp_b, tp_b + fp_b)
    rec_b = _ratio(tp_b, tp_b + fn_b)
    f1_b = _ratio(2 * tp_b, 2 * tp_b + fp_b + fn_b)
    return {
        "n": len(t),
        "threshold": float(threshold),
        "tp": int((t & p).sum()),
        "fp": int((~t & p).sum()),
        "fn": int((t & ~p).sum()),
        "tn": int((~t & ~p).sum()),
        "precision": _none(float(point_p)),
        "recall": _none(float(point_r)),
        "f1": _none(float(point_f)),
        "precision_ci": _ci(prec_b),
        "recall_ci": _ci(rec_b),
        "f1_ci": _ci(f1_b),
        "n_boot": int(n_boot),
        "n_undefined": int((np.isnan(prec_b) | np.isnan(rec_b)).sum()),
    }


def _positive_candidates(y_true, y_score):
    t = np.asarray(y_true, dtype=int) == 1
    s = np.asarray(y_score, dtype=float)
    return t, s, np.unique(s[t])[::-1]


def threshold_for_recall(y_true, y_score, target: float, weights=None) -> float | None:
    """Largest threshold whose weighted point recall is at least `target`."""
    t, s, cands = _positive_candidates(y_true, y_score)
    w = _weights(weights, len(t))
    total = w[t].sum()
    for c in cands:
        if total > 0 and w[t & (s >= c)].sum() / total >= target - 1e-12:
            return float(c)
    return None


def threshold_for_recall_lb(y_true, y_score, target: float, weights=None, strata=None,
                            clusters=None, n_boot: int = 2000, seed: int = 0,
                            alpha: float = 0.05) -> dict:
    """Largest threshold whose one-sided (1 - alpha) bootstrap lower bound of recall is at
    least `target`. The bootstrap resamples within strata, so per-stratum counts stay fixed.
    `point_recall` is the recall at that threshold on these rows (calibration only)."""
    t, s, cands = _positive_candidates(y_true, y_score)
    out = {"threshold": None, "recall_lower_bound": None, "point_recall": None,
           "target": float(target), "alpha": float(alpha), "n_boot": int(n_boot)}
    if not len(cands):
        return out
    w = _weights(weights, len(t))
    unit_of_row, counts, _ = _draw_counts(strata, clusters, n_boot, seed, n=len(t))
    k = counts.shape[1]
    pos_b = counts @ _unit_sums(w * t, unit_of_row, k)
    for c in cands:
        hit_w = w * (t & (s >= c))
        lb = np.nanpercentile(_ratio(counts @ _unit_sums(hit_w, unit_of_row, k), pos_b),
                              100 * alpha) if (pos_b > 0).any() else np.nan
        if not np.isnan(lb) and lb >= target - 1e-12:
            out.update(threshold=float(c), recall_lower_bound=float(lb),
                       point_recall=float(hit_w.sum() / w[t].sum()))
            return out
    return out


def reliability_bins(y_true, y_score, n_bins: int = 10, weights=None) -> list[dict]:
    y = np.asarray(y_true, dtype=float)
    s = np.clip(np.asarray(y_score, dtype=float), 0.0, 1.0)
    w = _weights(weights, len(y))
    idx = np.minimum((s * n_bins).astype(int), n_bins - 1)
    bins = []
    for b in range(n_bins):
        m = idx == b
        ws = w[m].sum()
        bins.append({
            "lo": b / n_bins,
            "hi": (b + 1) / n_bins,
            "n": int(m.sum()),
            "weight": float(ws),
            "mean_predicted": float((w[m] * s[m]).sum() / ws) if m.any() and ws > 0 else None,
            "observed": float((w[m] * y[m]).sum() / ws) if m.any() and ws > 0 else None,
        })
    return bins


def choice_confusion(true, pred) -> dict:
    """Accuracy and a nested count matrix {true_label: {pred_label: count}}."""
    pairs = list(zip(true, pred, strict=True))
    matrix: dict[str, dict[str, int]] = {}
    for a, b in pairs:
        row = matrix.setdefault(a, {})
        row[b] = row.get(b, 0) + 1
    correct = sum(a == b for a, b in pairs)
    return {"n": len(pairs), "accuracy": correct / len(pairs) if pairs else None,
            "matrix": matrix}

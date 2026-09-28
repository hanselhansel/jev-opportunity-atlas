"""Robustness checks for clustered estimates (leave-one-cluster-out, trimming, BH)."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np


def _cluster_contributions(
    values: np.ndarray, clusters: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (unique cluster ids, per-cluster sums, ids ordered heaviest first).

    Ordering is a stable sort on descending contribution, so ties keep the
    ascending cluster-id order produced by np.unique.
    """
    uniq, inverse = np.unique(clusters, return_inverse=True)
    contributions = np.zeros(uniq.shape[0], dtype=float)
    np.add.at(contributions, inverse, values)
    order = np.argsort(-contributions, kind="stable")
    return uniq, contributions, order


def leave_one_cluster_out(
    values: np.ndarray,
    clusters: np.ndarray,
    stat_fn: Callable[[np.ndarray], float] = np.mean,
    k: int = 10,
) -> dict:
    """Drop each of the k heaviest clusters in turn and recompute stat_fn."""
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    if values.shape[0] != clusters.shape[0]:
        raise ValueError("values and clusters must have the same length")
    uniq, contributions, order = _cluster_contributions(values, clusters)
    total = float(values.sum())
    max_cluster_share = float(contributions.max() / total) if total != 0 else 0.0
    n_try = min(int(k), uniq.shape[0])
    dropped = [uniq[i].item() for i in order[:n_try]]
    stats = [float(stat_fn(values[clusters != uniq[i]])) for i in order[:n_try]]
    return {
        "full": float(stat_fn(values)),
        "min": min(stats),
        "max": max(stats),
        "max_cluster_share": max_cluster_share,
        "flag": max_cluster_share > 0.10,
        "dropped": dropped,
    }


def drop_top_share(
    values: np.ndarray,
    clusters: np.ndarray,
    share: float = 0.01,
    stat_fn: Callable[[np.ndarray], float] = np.mean,
) -> dict:
    """Drop the heaviest ceil(share * n_clusters) clusters and recompute stat_fn."""
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    if values.shape[0] != clusters.shape[0]:
        raise ValueError("values and clusters must have the same length")
    uniq, _contributions, order = _cluster_contributions(values, clusters)
    n_clusters = uniq.shape[0]
    n_drop = max(1, math.ceil(share * n_clusters))
    if n_drop >= n_clusters:
        raise ValueError("share would remove every cluster; at least one must remain")
    drop_ids = [uniq[i] for i in order[:n_drop]]
    keep = ~np.isin(clusters, drop_ids)
    return {
        "full": float(stat_fn(values)),
        "estimate": float(stat_fn(values[keep])),
        "n_dropped": n_drop,
        "dropped": [u.item() for u in drop_ids],
    }


def author_capped_weights(authors: np.ndarray, k: int = 3) -> np.ndarray:
    """Per-item weights so each author's total weight is min(count, k)."""
    if k < 1:
        raise ValueError("k must be >= 1")
    authors = np.asarray(authors)
    _uniq, inverse, counts = np.unique(
        authors, return_inverse=True, return_counts=True
    )
    return np.minimum(1.0, k / counts[inverse]).astype(float)


def benjamini_hochberg(pvalues: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg rejections as a bool array in the original input order."""
    p = np.asarray(pvalues, dtype=float)
    if np.any((p < 0) | (p > 1)):
        raise ValueError("p-values must lie in [0, 1]")
    m = p.shape[0]
    rejected = np.zeros(m, dtype=bool)
    if m == 0:
        return rejected
    order = np.argsort(p, kind="stable")
    thresholds = (np.arange(1, m + 1) / m) * q
    passed = p[order] <= thresholds
    if np.any(passed):
        cutoff = int(np.max(np.nonzero(passed)))
        rejected[order[: cutoff + 1]] = True
    return rejected


def bootstrap_pvalue(reps: np.ndarray, null: float = 0.0) -> float:
    """Two-sided bootstrap p-value for the fraction of reps on each side of null."""
    reps = np.asarray(reps, dtype=float)
    reps = reps[~np.isnan(reps)]
    b = reps.shape[0]
    if b == 0:
        return 1.0
    lo = (1.0 + float((reps <= null).sum())) / (b + 1)
    hi = (1.0 + float((reps >= null).sum())) / (b + 1)
    return min(1.0, 2.0 * min(lo, hi))

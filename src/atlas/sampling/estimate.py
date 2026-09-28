"""Weighted estimates with a stratified, thread-clustered Rao-Wu bootstrap."""

from __future__ import annotations

import math

import numpy as np


def weighted_proportion(
    y,
    w,
    strata,
    clusters,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
    min_hits: int = 30,
    fpc=None,
    domain=None,
) -> dict:
    """Weighted proportion with a percentile cluster-bootstrap interval.

    Threads are not the sampling unit, so the cluster bootstrap is a
    conservative, model-based approximation. Threads crossing periods are
    treated as separate clusters per stratum (clusters are keyed by
    (stratum, cluster)). `fpc` holds the element sampling fraction per row as
    an approximation and must be constant within each stratum. `domain` is a
    boolean mask: the estimate and every replicate use sum(w*y*d)/sum(w*d) on
    the full sample; rows are never subset before resampling. Strata with one
    cluster contribute no variance and are counted in `single_cluster_strata`.
    """
    y = np.asarray(y, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    s = np.asarray(strata)
    c = np.asarray(clusters)
    d = np.ones(len(y), dtype=bool) if domain is None else np.asarray(domain, dtype=bool)
    f_arr = np.zeros(len(y)) if fpc is None else np.asarray(fpc, dtype=np.float64)

    wyd = w * y * d
    wd = w * d
    estimate = float(wyd.sum() / wd.sum())

    s_uniq, s_inv = np.unique(s, return_inverse=True)
    c_uniq, c_inv = np.unique(c, return_inverse=True)
    pair_uniq, cl = np.unique(s_inv * len(c_uniq) + c_inv, return_inverse=True)
    n_clusters = len(pair_uniq)
    cl_stratum = pair_uniq // len(c_uniq)  # stratum index of each dense cluster
    s_wyd = np.bincount(cl, weights=wyd, minlength=n_clusters)
    s_wd = np.bincount(cl, weights=wd, minlength=n_clusters)

    f_h = np.zeros(len(s_uniq))
    for h in range(len(s_uniq)):
        vals = f_arr[s_inv == h]
        if not np.all(vals == vals[0]):
            raise ValueError(f"fpc is not constant within stratum {s_uniq[h]!r}")
        f_h[h] = float(vals[0])

    m_h = np.bincount(cl_stratum, minlength=len(s_uniq))
    single = int(np.sum(m_h == 1))

    census = fpc is not None and bool(np.all(f_h >= 1.0 - 1e-12))
    if census:
        ci_low = ci_high = estimate
    else:
        rng = np.random.default_rng(seed)
        reps = np.empty(n_boot)
        done = 0
        while done < n_boot:
            block = min(100, n_boot - done)
            mult = np.ones((block, n_clusters))
            for h in range(len(s_uniq)):
                cols = np.nonzero(cl_stratum == h)[0]
                m = len(cols)
                if m < 2:
                    continue
                lam = math.sqrt(max(0.0, 1.0 - f_h[h]))
                r = rng.multinomial(m - 1, np.full(m, 1.0 / m), size=block)
                mult[:, cols] = 1.0 - lam + lam * (m / (m - 1.0)) * r
            num = mult @ s_wyd
            den = mult @ s_wd
            out = np.full(block, np.nan)
            np.divide(num, den, out=out, where=den != 0)
            reps[done : done + block] = out
            done += block
        ci_low, ci_high = (float(v) for v in np.nanquantile(reps, [alpha / 2, 1 - alpha / 2]))

    hits = int(np.sum((y == 1) & d))
    return {
        "estimate": estimate,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n": int(d.sum()),
        "weighted_n": float(wd.sum()),
        "hits": hits,
        "n_clusters": int(n_clusters),
        "single_cluster_strata": single,
        "too_few": bool(hits < min_hits),
        "method": "stratified cluster bootstrap, percentile",
        "n_boot": int(n_boot),
        "seed": int(seed),
    }

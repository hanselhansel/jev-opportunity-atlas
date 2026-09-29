"""Domain share rows for the site: share of firsthand problems in each domain.

The estimand is P(firsthand and domain = d) / P(firsthand) over the breadth
sample, by period and for the whole window. When gold labels exist for it (a
firsthand label on every gold item, and a domain label on every "yes"), both
parts are PPI++-corrected (``atlas.estimation.ppi.ppi_ratio``). Otherwise the
row is Jev's classification alone: the weighted share among comments Jev
screened as firsthand and faceted, with a stratified thread bootstrap interval,
marked ``qualifier = "as classified by Jev; unaudited"``.
"""

from __future__ import annotations

import math

import numpy as np

MIN_N = 30  # below this many classified comments, no interval is shown
MIN_GOLD = 10  # fewer usable gold items than this: no correction
UNAUDITED = "as classified by Jev; unaudited"
PERIODS = [f"P{i:02d}" for i in range(1, 13)]


def _codes(x) -> np.ndarray:
    return np.unique(np.asarray(x, dtype=object).astype(str), return_inverse=True)[1]


def boot_ratio(den, nums, w, strata, clusters, n_boot=2000, seed=0, alpha=0.05):
    """Percentile interval of sum(w*num)/sum(w*den) per column of ``nums``.

    Threads are resampled with replacement within strata; the unit is the pair
    (stratum, thread), as in ``atlas.estimation.ppi``.
    """
    den = np.asarray(den, dtype=float)
    nums = np.asarray(nums, dtype=float).reshape(den.size, -1)
    w = np.asarray(w, dtype=float)
    cols = np.column_stack([w * den, w[:, None] * nums])
    pairs, inv = np.unique(
        np.stack([_codes(strata), _codes(clusters)], axis=1),
        axis=0,
        return_inverse=True,
    )
    sums = np.zeros((pairs.shape[0], cols.shape[1]))
    np.add.at(sums, inv.ravel(), cols)
    rng = np.random.default_rng(seed)
    total = np.zeros((n_boot, cols.shape[1]))
    for s in np.unique(pairs[:, 0]):
        idx = np.flatnonzero(pairs[:, 0] == s)
        m = idx.size
        counts = rng.multinomial(m, np.full(m, 1.0 / m), size=n_boot)
        total += counts @ sums[idx]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = total[:, 1:] / total[:, [0]]
    lo, hi = np.nanquantile(ratios, [alpha / 2, 1 - alpha / 2], axis=0)
    return lo, hi


def _finite(x) -> float | None:
    return float(x) if x is not None and math.isfinite(x) else None


def _ppi(sub, gold, d, n_boot, seed) -> dict | None:
    from atlas.estimation.ppi import ppi_ratio

    num_all = [float(r["domain"] == d) for r in sub]
    den_all = [float(r["domain"] is not None) for r in sub]
    num_gold = [float(g["fh"] and g["domain"] == d) for g in gold]
    num_gold_hat = [float(g["row"]["domain"] == d) for g in gold]
    den_gold = [float(g["fh"]) for g in gold]
    den_gold_hat = [float(g["row"]["domain"] is not None) for g in gold]
    with np.errstate(divide="ignore", invalid="ignore"):
        res = ppi_ratio(
            (num_all, num_gold, num_gold_hat),
            (den_all, den_gold, den_gold_hat),
            w_all=[r["weight"] for r in sub],
            w_gold=[g["row"]["weight"] for g in gold],
            sel_prob_gold=[g["sel"] for g in gold],
            strata_all=[r["stratum"] for r in sub],
            strata_gold=[g["row"]["stratum"] for g in gold],
            clusters_all=[r["story_id"] for r in sub],
            clusters_gold=[g["row"]["story_id"] for g in gold],
            n_boot=n_boot,
            seed=seed,
        )
    est = _finite(res["estimate"])
    if est is None:
        return None
    return {"share": est, "lo": _finite(res["ci_low"]), "hi": _finite(res["ci_high"])}


def _denominator(n_fac: int, period: str) -> str:
    where = "" if period == "all" else f" in {period}"
    return f"of {n_fac:,} sampled comments Jev screened as firsthand{where}"


def domain_share_rows(frame, gold, run_id, question_set, n_boot=2000, seed=0):
    """Rows for the ``domain_share`` table plus a ``qualifier`` column.

    ``frame``: one dict per screened comment with comment_id, story_id,
    stratum, weight, period, and domain (Jev's facets choice; None when not
    faceted). ``gold``: dict comment_id -> {"fh": bool, "domain": str | None,
    "sel": selection probability}, already limited to usable gold items.
    """
    domains = sorted({r["domain"] for r in frame if r["domain"] is not None})
    rows = []
    for period in [*PERIODS, "all"]:
        sub = [r for r in frame if period == "all" or r["period"] == period]
        fac = [r for r in sub if r["domain"] is not None]
        if not fac:
            continue
        sub_gold = [
            {**gold[r["comment_id"]], "row": r} for r in sub if r["comment_id"] in gold
        ]
        nums = np.array([[float(r["domain"] == d) for d in domains] for r in fac])
        w = np.array([r["weight"] for r in fac], dtype=float)
        naive = (w @ nums) / w.sum()
        lo, hi = boot_ratio(
            np.ones(len(fac)),
            nums,
            w,
            [r["stratum"] for r in fac],
            [r["story_id"] for r in fac],
            n_boot,
            seed,
        )
        for j, d in enumerate(domains):
            n = int(nums[:, j].sum())
            est = None
            if len(sub_gold) >= MIN_GOLD:
                est = _ppi(sub, sub_gold, d, n_boot, seed)
            if est is not None:
                qualifier = f"PPI-corrected with {len(sub_gold)} gold labels"
            else:
                est = {
                    "share": float(naive[j]),
                    "lo": _finite(lo[j]),
                    "hi": _finite(hi[j]),
                }
                qualifier = UNAUDITED
            too_few = n < MIN_N
            rows.append(
                {
                    "lane": "breadth",
                    "domain": d,
                    "period": period,
                    "n": n,
                    "weighted_share": est["share"],
                    "ci_low": None if too_few else est["lo"],
                    "ci_high": None if too_few else est["hi"],
                    "too_few": too_few,
                    "badge": "estimated",
                    "run_id": run_id,
                    "question_set": question_set,
                    "denominator": _denominator(len(fac), period),
                    "qualifier": qualifier,
                }
            )
    return rows

"""S6: launch shares per card, the match rate, and the builder-to-complaint
ratio.

Every estimate is a weighted share over the launch sample, bootstrapped by
month stratum with each story its own cluster (R = 1000, seed 0) — the same
resample index is reused across cards and the match indicator, so all figures
come from one joint set of replicates. The ratio pairs the launch replicates
with the complaint-share replicates produced by S1's bootstrap.
"""

from __future__ import annotations

import numpy as np

MIN_CARD_P = 0.5
SPARSE_N = 30
R_DEFAULT = 1000
SEED = 0


def _est(est, reps, n):
    """An Est dict, or None when the estimate is not computable."""
    reps = np.asarray(reps, dtype=np.float64)
    reps = reps[np.isfinite(reps)]
    if est is None or not np.isfinite(est) or reps.size == 0:
        return None
    return {
        "est": float(est),
        "lo50": float(np.percentile(reps, 25.0)),
        "hi50": float(np.percentile(reps, 75.0)),
        "lo95": float(np.percentile(reps, 2.5)),
        "hi95": float(np.percentile(reps, 97.5)),
        "n": int(n),
        "sparse": bool(n < SPARSE_N),
    }


def _rep_shares(periods, weights, X, R=R_DEFAULT, seed=SEED):
    """Weighted column shares of X plus stratified bootstrap replicates.

    Per stratum h, resample its m launches with replacement (multinomial
    counts); a replicate share is sum(count * weight * X) over the constant
    denominator sum(weight) = N.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    periods = np.asarray(periods)
    weights = np.asarray(weights, dtype=np.float64)
    X = np.asarray(X, dtype=np.float64)
    total = float(weights.sum())
    reps = np.zeros((R, X.shape[1]))
    for h in np.unique(periods):
        idx = np.nonzero(periods == h)[0]
        m = idx.size
        counts = rng.multinomial(m, np.full(m, 1.0 / m), size=R)
        reps += (counts * weights[idx]) @ X[idx]
    return (weights @ X) / total, reps / total


def _ratio_est(est_launch, reps_launch, complaint, n):
    """launch_share / complaint_share; None when the denominator is unknown
    or zero. Replicate pairs line up row-wise: the two populations are
    independent, so index pairing draws from the product distribution."""
    if not complaint or complaint.get("est") is None:
        return None
    c_est = float(complaint["est"])
    c_reps_raw = complaint.get("reps")
    if c_est <= 0.0 or c_reps_raw is None:
        return None
    c_reps = np.asarray(c_reps_raw, dtype=np.float64)
    reps_launch = np.asarray(reps_launch, dtype=np.float64)
    m = min(c_reps.size, reps_launch.size)
    if m == 0:
        return None
    den = c_reps[:m]
    ok = den > 0.0
    if not ok.any():
        return None
    reps = np.full(m, np.nan)
    reps[ok] = reps_launch[:m][ok] / den[ok]
    return _est(est_launch / c_est, reps, n)


def builder_shares(assign_rows, sample, story_cards, R=R_DEFAULT, seed=SEED):
    """(builders, per_card) from the builders-run assignments.

    assign_rows carry comment_id = story_id plus card_id/card_p; `sample` is
    the builders-<seed> table (story_id, period, weight); `story_cards` maps
    card_id -> {"est", "reps"} complaint shares from the S1 bootstrap.
    """
    rows = sample.to_pylist() if hasattr(sample, "to_pylist") else list(sample)
    assigned: dict[int, str | None] = {}
    for a in assign_rows:
        card = a.get("card_id")
        p = a.get("card_p") or 0.0
        assigned[int(a["comment_id"])] = (
            card if card not in (None, "none") and p >= MIN_CARD_P else None
        )
    ids = [int(r["story_id"]) for r in rows]
    periods = [r["period"] for r in rows]
    weights = np.array([float(r["weight"]) for r in rows], dtype=np.float64)
    n = len(ids)
    story_cards = story_cards or {}
    card_ids = sorted(
        {c for c in assigned.values() if c is not None} | set(story_cards)
    )
    hit = np.array(
        [[1.0 if assigned.get(i) else 0.0 for i in ids]], dtype=np.float64
    )
    if card_ids:
        X = np.column_stack(
            [
                np.fromiter(
                    (1.0 if assigned.get(i) == c else 0.0 for i in ids),
                    dtype=np.float64,
                    count=n,
                )
                for c in card_ids
            ]
        )
    else:
        X = np.zeros((n, 0))
    share_est, share_reps = _rep_shares(periods, weights, X, R, seed)
    m_est, m_reps = _rep_shares(periods, weights, hit.T, R, seed)
    builders = {
        "n_sampled": n,
        "n_population": round(float(weights.sum())),
        "match_rate": _est(float(m_est[0]), m_reps[:, 0], n),
    }
    per_card = {}
    for j, c in enumerate(card_ids):
        cnt = sum(1 for i in ids if assigned.get(i) == c)
        per_card[c] = {
            "launch_share": _est(
                float(share_est[j]), share_reps[:, j], cnt
            ),
            "ratio": _ratio_est(
                float(share_est[j]),
                share_reps[:, j],
                story_cards.get(c),
                cnt,
            ),
        }
    return builders, per_card

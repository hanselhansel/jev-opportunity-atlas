"""S3: the opportunity score, weight presets, and bootstrap rank stability.

Every raw signal becomes a midrank percentile among cards with at least
``MIN_PROBLEMS`` firsthand problems; a missing signal stays ``None`` and the
weighted mean renormalizes over what is present. ``rank_quantiles`` rerank
the balanced score inside each bootstrap replicate of share, change, paid,
and severity3 (the other components stay at their point percentile), so each
card carries the ventiles of its rank distribution rather than a point rank.

Component names match the essay's vocabulary in ``essay/charts/opportunity.js``:
``growth`` is ``change``, ``severe`` is ``severity3``, ``underbuilt`` is
``-log(builders.ratio)`` called ``launch_ratio``.
"""

from __future__ import annotations

import math

import numpy as np

COMPONENTS = [
    "share",
    "change",
    "paid",
    "unsolved",
    "severity3",
    "launch_ratio",
    "reliability",
    "customers",
]
REPLICATED = ("share", "change", "paid", "severity3")
MIN_PROBLEMS = 50

PRESETS = {
    "balanced": {k: 1.0 for k in COMPONENTS},
    "growth": {
        **{k: 0.5 for k in COMPONENTS},
        "share": 1.0,
        "change": 3.0,
    },
    "paid_pain": {
        **{k: 0.5 for k in COMPONENTS},
        "paid": 3.0,
        "severity3": 2.0,
        "unsolved": 2.0,
    },
    "underbuilt": {
        **{k: 0.5 for k in COMPONENTS},
        "launch_ratio": 3.0,
        "unsolved": 2.0,
    },
}


def _avg_ranks(v):
    """Average ranks 1..k of a finite float vector, smallest value first."""
    v = np.asarray(v, dtype=float)
    k = v.size
    order = np.argsort(v, kind="stable")
    sv = v[order]
    ranks = np.empty(k, dtype=float)
    i = 0
    while i < k:
        j = i + 1
        while j < k and sv[j] == sv[i]:
            j += 1
        ranks[order[i:j]] = 0.5 * (i + 1 + j)
        i = j
    return ranks


def _pcts(vals):
    """Midrank percentiles ``(rank - 0.5)/k``; NaN where the value is NaN."""
    vals = np.asarray(vals, dtype=float)
    out = np.full(vals.shape, np.nan)
    mask = np.isfinite(vals)
    k = int(mask.sum())
    if k:
        out[mask] = (_avg_ranks(vals[mask]) - 0.5) / k
    return out


def _rep_pcts(M, eligible):
    """Column-wise midrank percentiles of an (m, R) replicate matrix."""
    out = np.full(M.shape, np.nan)
    for r in range(M.shape[1]):
        v = M[:, r]
        mask = eligible & np.isfinite(v)
        if int(mask.sum()):
            out[mask, r] = (_avg_ranks(v[mask]) - 0.5) / int(mask.sum())
    return out


def _est_of(node) -> float | None:
    v = node.get("est") if isinstance(node, dict) else None
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def _point_value(card, comp) -> float | None:
    if comp == "share":
        return _est_of(card.get("share"))
    if comp == "change":
        ch = card.get("change") or {}
        v = ch.get("shrunk")
        return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None
    if comp == "paid":
        return _est_of((card.get("coping") or {}).get("commercial"))
    if comp == "unsolved":
        return _est_of((card.get("unsolved") or {}).get("unsolved"))
    if comp == "severity3":
        return _est_of((card.get("quality") or {}).get("severe3"))
    if comp == "launch_ratio":
        r = _est_of((card.get("builders") or {}).get("ratio"))
        return -math.log(r) if r is not None and r > 0 else None
    if comp in ("reliability", "customers"):
        return _est_of((card.get("costs") or {}).get(comp))
    return None


def weighted_score(components, weights) -> float | None:
    """Weighted mean of non-null components, renormalized; an all-zero weight
    vector falls back to equal weights."""
    w = {k: float((weights or {}).get(k) or 0.0) for k in COMPONENTS}
    if sum(w.values()) <= 0:
        w = {k: 1.0 for k in COMPONENTS}
    num = den = 0.0
    for k in COMPONENTS:
        v = (components or {}).get(k)
        if v is None or w[k] <= 0 or not math.isfinite(v):
            continue
        num += w[k] * float(v)
        den += w[k]
    return num / den if den else None


def _fill_rank_quantiles(cards_score, ids, scored_mask, pct, rep_cards) -> None:
    sids = [cid for cid, ok in zip(ids, scored_mask) if ok]
    if not sids or not rep_cards:
        return
    R = max(
        (np.asarray(v).size for d in rep_cards.values() for v in d.values()),
        default=0,
    )
    if R == 0:
        return
    cube = np.full((len(sids), R, len(COMPONENTS)), np.nan)
    for ci, comp in enumerate(COMPONENTS):
        if comp in REPLICATED:
            M = np.full((len(sids), R), np.nan)
            for j, cid in enumerate(sids):
                arr = np.asarray(
                    (rep_cards.get(cid) or {}).get(comp, []), dtype=float
                ).ravel()
                m = min(R, arr.size)
                if m:
                    M[j, :m] = arr[:m]
            eligible = np.array(
                [pct[comp].get(cid) is not None for cid in sids]
            )
            cube[:, :, ci] = _rep_pcts(M, eligible)
        else:
            for j, cid in enumerate(sids):
                p = pct[comp].get(cid)
                if p is not None:
                    cube[j, :, ci] = p
    cnt = np.isfinite(cube).sum(axis=2)
    with np.errstate(invalid="ignore"):
        smat = np.where(
            cnt > 0, np.nansum(cube, axis=2) / np.where(cnt > 0, cnt, 1), np.nan
        )
    ranks = {cid: [] for cid in sids}
    id_arr = np.asarray(sids, dtype=object)
    for r in range(R):
        s = smat[:, r]
        ok = np.isfinite(s)
        if not ok.any():
            continue
        for cid, rv in zip(id_arr[ok], _avg_ranks(-s[ok])):
            ranks[cid].append(float(rv))
    qpoints = np.arange(0.05, 1.001, 0.05)
    for cid in sids:
        if ranks[cid]:
            q = np.quantile(np.asarray(ranks[cid]), qpoints)
            cards_score[cid]["rank_quantiles"] = [
                max(1, round(v)) for v in q
            ]


def build_scores(story, reps=None):
    """``(cards_score, presets)``: per-card ``{"components", "rank_quantiles"}``
    plus the four weight presets. ``reps`` maps card id to per-component
    replicate arrays for the components in ``REPLICATED``."""
    cards = story.get("cards") or []
    ids = [c["id"] for c in cards]
    scored_mask = np.array(
        [(c.get("n_problems") or 0) >= MIN_PROBLEMS for c in cards]
    )
    point = {
        c["id"]: {k: _point_value(c, k) for k in COMPONENTS} for c in cards
    }
    pct: dict[str, dict] = {k: {} for k in COMPONENTS}
    id_arr = np.asarray(ids, dtype=object)
    for comp in COMPONENTS:
        vals = np.array(
            [
                point[cid][comp] if point[cid][comp] is not None else np.nan
                for cid in ids
            ]
        )
        p = _pcts(np.where(scored_mask, vals, np.nan))
        for cid, pv in zip(id_arr, p):
            if np.isfinite(pv):
                pct[comp][cid] = float(pv)
    cards_score = {
        cid: {
            "components": {k: pct[k].get(cid) for k in COMPONENTS},
            "rank_quantiles": [],
        }
        for cid in ids
    }
    _fill_rank_quantiles(cards_score, ids, scored_mask, pct, reps or {})
    return cards_score, {k: dict(v) for k, v in PRESETS.items()}


def _fcol(fh, name):
    """A float column; all-NaN when the frame lacks it."""
    import pandas as pd

    if name not in fh.columns:
        return np.full(len(fh), np.nan)
    return pd.to_numeric(fh[name], errors="coerce").to_numpy(dtype=float)


def component_reps(fh, rep, card_ids):
    """``{card: {comp: (R,) replicate values}}`` for ``REPLICATED``.

    ``rep`` must have been built on ``fh`` so the resample index aligns.
    ``change`` replicates carry the same per-card shrink factor the point
    estimate uses; ``paid`` and ``severity3`` are within-card shares
    (denominator = the card's own rows).
    """
    from atlas.story.core import PERIODS
    from atlas.story.unsolved import col_ratios

    card_ids = list(card_ids)
    if not card_ids or len(fh) == 0:
        return {}
    k = len(card_ids)
    w = fh["weight"].to_numpy(dtype=float)
    card_arr = fh["card"].astype(object).to_numpy()
    X = np.column_stack([(card_arr == c) for c in card_ids]).astype(float)
    one = np.ones((len(fh), k))
    _, share_reps = col_ratios(rep, w, X, one)
    period = fh["period"].astype(object).to_numpy()
    h1 = np.isin(period, list(PERIODS[:6]))[:, None].astype(float)
    h2 = np.isin(period, list(PERIODS[6:]))[:, None].astype(float)
    e1, r1 = col_ratios(rep, w, X * h1, np.tile(h1, (1, k)))
    e2, r2 = col_ratios(rep, w, X * h2, np.tile(h2, (1, k)))
    diff_est, diff_reps = e2 - e1, r2 - r1
    se = np.nanstd(diff_reps, axis=0)
    ok = np.isfinite(diff_est) & np.isfinite(se)
    tau2 = 0.0
    if int(ok.sum()) >= 2:
        tau2 = max(
            0.0, float(np.var(diff_est[ok]) - np.mean(se[ok] ** 2))
        )
    shrink = np.where(
        ok & (tau2 + se**2 > 0), tau2 / (tau2 + se**2), np.nan
    )
    change_reps = diff_reps * shrink[None, :]
    com = np.zeros(len(fh), dtype=bool)
    for q in ("f_paid", "f_switched", "f_abandoned"):
        com |= _fcol(fh, q) >= 0.5
    sev = _fcol(fh, "severity") >= 2.5
    _, paid_reps = col_ratios(rep, w, X * com[:, None], X)
    _, sev_reps = col_ratios(rep, w, X * sev[:, None], X)
    return {
        c: {
            "share": share_reps[:, j],
            "change": change_reps[:, j],
            "paid": paid_reps[:, j],
            "severity3": sev_reps[:, j],
        }
        for j, c in enumerate(card_ids)
    }

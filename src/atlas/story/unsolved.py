"""S3: the replies join — per-card unsolved and author-solved shares.

``replies/unsolved_by_problem.parquet`` (one row per problem comment the
replies run measured) joins to the phase-2 firsthand population on
``comment_id``. A card gets estimates only when at least ``MIN_ANSWERED`` of
its problems were measured; below the gate the entry stays ``None`` so the
score drops the component instead of treating it as zero.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from atlas.story import boot

MIN_ANSWERED = 30


def col_ratios(rep, weight, nums, dens):
    """Per-column weighted shares: ``est[k] = sum(w*num_k)/sum(w*den_k)`` with
    replicate ratios over the same resampled denominators. Returns
    ``(est[k], reps[R,k])``."""
    nums = np.asarray(nums, dtype=float)
    dens = np.asarray(dens, dtype=float)
    t = rep.totals(np.column_stack([dens, nums]))
    k = nums.shape[1]
    with np.errstate(divide="ignore", invalid="ignore"):
        reps = t[:, k:] / t[:, :k]
    weight = np.asarray(weight, dtype=float)
    dsum = (weight[:, None] * dens).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        est = (weight[:, None] * nums).sum(axis=0) / np.where(
            dsum > 0, dsum, np.nan
        )
    return est, reps


def _reply_rows(replies_parquet) -> dict[int, dict]:
    """``comment_id -> row`` from a path, a table, or an iterable of dicts."""
    if replies_parquet is None:
        return {}
    if hasattr(replies_parquet, "to_pylist"):
        rows = replies_parquet.to_pylist()
    elif isinstance(replies_parquet, (str, Path)):
        p = Path(replies_parquet)
        if not p.exists():
            return {}
        rows = pq.read_table(p).to_pylist()
    else:
        rows = list(replies_parquet)
    return {
        int(r["comment_id"]): r for r in rows if r.get("comment_id") is not None
    }


def card_unsolved(
    frame, replies_parquet, rep=None, R=1000, seed=0, min_answered=MIN_ANSWERED
):
    """``{card: {"unsolved": Est, "author_solved": Est} | None}``.

    ``unsolved`` is the weighted share of the card's measured problems with
    ``unsolved == True``; ``author_solved`` the weighted share with
    ``author_says_solved == "solved"``. Both share the measured-problems
    denominator of the card, bootstrapped with the frame's joint replicates.
    """
    fh = frame[(frame["phase"] == "pos") & frame["firsthand"]]
    cards = sorted(c for c in fh["card"].unique() if isinstance(c, str))
    out = {c: None for c in cards}
    by_cid = _reply_rows(replies_parquet)
    if not cards or not by_cid or len(fh) == 0:
        return out
    if rep is None:
        rep = boot.Replicates(fh, R=R, seed=seed)
    ucol = fh["comment_id"].map(lambda c: by_cid.get(int(c)))
    answered = ucol.map(lambda r: isinstance(r, dict)).to_numpy(dtype=bool)
    is_uns = ucol.map(
        lambda r: bool(r.get("unsolved")) if isinstance(r, dict) else False
    ).to_numpy(dtype=bool)
    is_sol = ucol.map(
        lambda r: isinstance(r, dict) and r.get("author_says_solved") == "solved"
    ).to_numpy(dtype=bool)
    card_arr = fh["card"].astype(object).to_numpy()
    den = np.column_stack(
        [(card_arr == c) & answered for c in cards]
    ).astype(float)
    w = fh["weight"].to_numpy(dtype=float)
    est_u, rep_u = col_ratios(rep, w, den * is_uns[:, None], den)
    est_s, rep_s = col_ratios(rep, w, den * is_sol[:, None], den)
    for k, c in enumerate(cards):
        n = int(den[:, k].sum())
        if n < min_answered:
            continue
        u = boot.summarize(est_u[k], rep_u[:, k], n)
        s = boot.summarize(est_s[k], rep_s[:, k], n)
        if u is None or s is None:
            continue
        out[c] = {"unsolved": u, "author_solved": s}
    return out

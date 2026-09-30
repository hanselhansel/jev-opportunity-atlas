"""Per-card concentration: how much of a card sits in its biggest clusters.

``top1_thread`` and ``top3_threads`` are the weighted shares of the card's
problems in its single largest and three largest threads; ``top1_author``
and ``top3_authors`` the same over authors. The null bands come from
reassigning the card's problems to clusters drawn with probability
proportional to each cluster's total firsthand problem count — the shares a
card would show if it were sprinkled across the population at random.
``flagged`` is the pre-registered rule: on cards with at least ``MIN_N``
problems, ``top1_thread > 0.30 or top1_author > 0.10``; thinner cards get
``None``.
"""

from __future__ import annotations

import numpy as np

from atlas.story.io import MIN_N

TOP_K = 3
# Pre-registered concentration flag: a card is concentrated when one thread
# holds over 30% of its problems, or one author over 10%.
FLAG_TOP1_THREAD = 0.30
FLAG_TOP1_AUTHOR = 0.10


def _placed(frame):
    return frame[
        (frame["phase"] == "pos")
        & frame["firsthand"]
        & frame["card"].notna()
    ]


def _top_share(keys, weights, k: int = TOP_K) -> float | None:
    """Weighted share of the k largest groups over the rows given."""
    totals: dict[object, float] = {}
    for key, w in zip(keys, weights):
        totals[key] = totals.get(key, 0.0) + float(w)
    s = sum(totals.values())
    if s <= 0:
        return None
    top = sorted(totals.values(), reverse=True)[:k]
    return float(sum(top) / s)


def _pop_probs(fh, col: str) -> np.ndarray:
    """P(draw) proportional to each cluster's firsthand problem count."""
    counts = fh.groupby(fh[col].astype(object)).size().to_numpy(dtype=float)
    return counts / counts.sum()


def _null_band(rng, probs: np.ndarray, n: int, sims: int):
    """2.5/97.5 percentiles of the simulated top-3 share for n problems."""
    if n <= 0 or probs.size == 0:
        return [None, None]
    draws = rng.choice(
        probs.size, size=(int(sims), n), p=probs, replace=True
    )
    shares = np.empty(int(sims))
    for s in range(int(sims)):
        counts = np.bincount(draws[s], minlength=probs.size)
        shares[s] = np.sort(counts)[-TOP_K:].sum() / n
    lo, hi = np.quantile(shares, [0.025, 0.975])
    return [float(lo), float(hi)]


def card_concentration(frame, sims: int = 500, seed: int = 0) -> dict:
    """``{card: {top1_*, top3_*, null_*, flagged}}``."""
    fh = _placed(frame)
    cards = sorted(
        fh["card"].unique()
        if frame.attrs.get("cardset") is None
        else frame.attrs["cardset"].cards
    )
    thread_probs = _pop_probs(fh, "story_id") if len(fh) else np.array([])
    fh_a = fh[fh["author"].notna()]
    author_probs = (
        _pop_probs(fh_a, "author") if len(fh_a) else np.array([])
    )
    rng = np.random.default_rng(seed)
    card_vals = fh["card"].astype(object).to_numpy()
    out = {}
    for card in cards:
        sub = fh[card_vals == card]
        w = sub["weight"].to_numpy(dtype=float)
        n = len(sub)
        t_keys = sub["story_id"].astype(object).to_numpy()
        top1_t = _top_share(t_keys, w, k=1)
        top_t = _top_share(t_keys, w)
        sub_a = sub[sub["author"].notna()]
        a_keys = sub_a["author"].astype(object).to_numpy()
        a_w = sub_a["weight"].to_numpy(dtype=float)
        top1_a = _top_share(a_keys, a_w, k=1)
        top_a = _top_share(a_keys, a_w)
        band_t = _null_band(rng, thread_probs, n, sims)
        band_a = _null_band(
            rng, author_probs, int(sub_a.shape[0]), sims
        )
        flagged = None
        if n >= MIN_N:
            flagged = any(
                v is not None and v > bar
                for v, bar in (
                    (top1_t, FLAG_TOP1_THREAD),
                    (top1_a, FLAG_TOP1_AUTHOR),
                )
            )
        out[card] = {
            "top1_thread": top1_t,
            "top1_author": top1_a,
            "top3_threads": top_t,
            "top3_authors": top_a,
            "null_threads": band_t,
            "null_authors": band_a,
            "flagged": flagged,
        }
    return out

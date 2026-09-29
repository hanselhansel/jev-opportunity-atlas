"""Per-card concentration: how much of a card sits in its biggest clusters.

``top3_threads`` is the weighted share of the card's problems in its three
largest threads; ``top3_authors`` the same over authors. The null bands come
from reassigning the card's problems to clusters drawn with probability
proportional to each cluster's total firsthand problem count — the shares a
card would show if it were sprinkled across the population at random.
``flagged`` is true when either observed value clears its band's top.
"""

from __future__ import annotations

import numpy as np

TOP_K = 3


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
    """``{card: {top3_threads, top3_authors, null_*, flagged}}``."""
    fh = _placed(frame)
    cards = sorted(
        fh["card"].unique()
        if frame.attrs.get("cardset") is None
        else frame.attrs["cardset"].all_cards
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
        top_t = _top_share(sub["story_id"].astype(object).to_numpy(), w)
        sub_a = sub[sub["author"].notna()]
        top_a = _top_share(
            sub_a["author"].astype(object).to_numpy(),
            sub_a["weight"].to_numpy(dtype=float),
        )
        band_t = _null_band(rng, thread_probs, n, sims)
        band_a = _null_band(
            rng, author_probs, int(sub_a.shape[0]), sims
        )
        flagged = (
            top_t is not None
            and band_t[1] is not None
            and top_t > band_t[1]
        ) or (
            top_a is not None
            and band_a[1] is not None
            and top_a > band_a[1]
        )
        out[card] = {
            "top3_threads": top_t,
            "top3_authors": top_a,
            "null_threads": band_t,
            "null_authors": band_a,
            "flagged": bool(flagged),
        }
    return out

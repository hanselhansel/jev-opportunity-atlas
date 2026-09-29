"""Per-card signal shares: coping behavior, stated costs, pain quality.

Each signal is the weighted share of the card's problems (phase-2 ``pos``
rows that are firsthand and placed on the card) carrying the facet: a yes/no
facet counts when its ``f_<q>`` noul is >= 0.5, and the severity/specificity
scores count at >= 2.5. Intervals come from one ``boot.Replicates`` per card,
so every share of the same card is jointly resampled. ``commercial`` is the
share with any of paid, switched, or abandoned — a problem counts once.
"""

from __future__ import annotations

import numpy as np

from atlas.story.boot import Replicates, summarize

MIN_NOUL = 0.5
MIN_SCORE = 2.5

COPING = {
    "paid": "f_paid",
    "switched": "f_switched",
    "abandoned": "f_abandoned",
    "workaround": "f_workaround",
}
COSTS = {
    "money": "f_cost_money",
    "time": "f_cost_time",
    "reliability": "f_cost_reliability",
    "customers": "f_cost_customers",
}
COMMERCIAL = ("paid", "switched", "abandoned")


def _flags(sub, col: str, cutoff: float) -> np.ndarray:
    if col not in sub:
        return np.zeros(len(sub), dtype=bool)
    v = sub[col].to_numpy(dtype=float, na_value=np.nan)
    return v >= cutoff


def _share(rep: Replicates, flag: np.ndarray, den: np.ndarray, n: int):
    point, reps = rep.ratio(flag.astype(float), den)
    return summarize(point[0], reps[:, 0], n)


def _card_ids(frame, sub_all):
    cs = frame.attrs.get("cardset")
    if cs is not None:
        return sorted(cs.all_cards)
    return sorted(c for c in sub_all["card"].unique() if c is not None)


def card_signals(frame, R: int = 1000, seed: int = 0) -> dict:
    """``{card: {coping, costs, quality}}``; every share is an Est."""
    fh = frame[
        (frame["phase"] == "pos")
        & frame["firsthand"]
        & frame["card"].notna()
    ]
    cards = _card_ids(frame, fh)
    out = {}
    for card in cards:
        sub = fh[fh["card"] == card]
        n = len(sub)
        rep = Replicates(sub, R=R, seed=seed)
        den = np.ones(n)
        flags = {k: _flags(sub, col, MIN_NOUL) for k, col in COPING.items()}
        coping = {
            k: _share(rep, f, den, n) for k, f in flags.items()
        }
        commercial = np.zeros(n, dtype=bool)
        for k in COMMERCIAL:
            commercial |= flags[k]
        coping["commercial"] = _share(rep, commercial, den, n)
        costs = {
            k: _share(rep, _flags(sub, col, MIN_NOUL), den, n)
            for k, col in COSTS.items()
        }
        quality = {
            "severe3": _share(rep, _flags(sub, "severity", MIN_SCORE), den, n),
            "specific3": _share(
                rep, _flags(sub, "specificity", MIN_SCORE), den, n
            ),
        }
        out[card] = {"coping": coping, "costs": costs, "quality": quality}
    return out

"""Specification ranks: each card's rank under alternative counting rules.

``main_rank`` ranks cards by weighted share of firsthand problems (the
counting rule the essay publishes). The alternatives re-rank the same frame
under stricter or deduplicated counting — ``card_p_0.7`` needs card_p >= 0.7,
``one_per_thread`` and ``one_per_author`` collapse each card x cluster cell
to its max weight, and ``para1``/``para2`` count unweighted card labels in
the paraphrase robustness runs. Rows are the union of every alternative's
top 20 so a card that only survives one rule still shows its wobble.
"""

from __future__ import annotations

import numpy as np
import pyarrow.parquet as pq

from atlas import paths

TOP_N = 20
CARD_P_ALT = 0.7
ALT_KEYS = (
    "card_p_0.7",
    "one_per_thread",
    "one_per_author",
    "para1",
    "para2",
)


def _ranks(scores: dict, cards: list) -> dict:
    """Competition rank: 1 + the count of cards with a strictly higher score."""
    vals = {c: float(scores.get(c, 0.0)) for c in cards}
    return {
        c: 1 + sum(v2 > v for v2 in vals.values()) for c, v in vals.items()
    }


def _top(scores: dict, cards: list, n: int = TOP_N) -> set:
    ranked = sorted(cards, key=lambda c: (-scores.get(c, 0.0), c))
    return {c for c in ranked[:n] if scores.get(c, 0.0) > 0}


def _dedup_max(sub, key) -> dict:
    """Score per card: sum of the max weight in each (card, key) cell."""
    scores: dict[str, float] = {}
    seen: dict[tuple, float] = {}
    for i, (card, k, w) in enumerate(
        zip(
            sub["card"].astype(object),
            sub[key].astype(object),
            sub["weight"],
        )
    ):
        missing = k is None or (isinstance(k, float) and np.isnan(k))
        cell = (card, i) if missing else (card, k)
        w = float(w)
        if w > seen.get(cell, float("-inf")):
            seen[cell] = w
    for (card, _), w in seen.items():
        scores[card] = scores.get(card, 0.0) + w
    return scores


def _para_counts(run_id, version: str, resolve=None) -> dict:
    """Unweighted card counts in a paraphrase run's assignments file."""
    if not run_id:
        return {}
    path = paths.run_dir(run_id) / f"assignments-{version}.parquet"
    if not path.exists():
        return {}
    scores: dict[str, float] = {}
    for r in pq.read_table(path, columns=["card_id"]).to_pylist():
        c = r.get("card_id")
        if c in (None, "none"):
            continue
        if resolve is not None:
            c = resolve(c)
            if c is None:
                continue
        scores[c] = scores.get(c, 0.0) + 1.0
    return scores


def spec_ranks(frame, para_runs: dict | None = None) -> list:
    """``[{card, main_rank, alt_ranks: {alt_key: int}}]`` over the union."""
    fh = frame[
        (frame["phase"] == "pos")
        & frame["firsthand"]
        & frame["card"].notna()
    ]
    cs = frame.attrs.get("cardset")
    cards = sorted(cs.cards if cs is not None else fh["card"].unique())
    version = cs.version if cs is not None else None
    resolve = getattr(cs, "try_resolve", None)
    card_p = fh["card_p"].to_numpy(dtype=float, na_value=np.nan)
    strict = fh[card_p >= CARD_P_ALT]
    scores = {
        "card_p_0.7": strict.groupby(strict["card"].astype(object))["weight"]
        .sum()
        .to_dict(),
        "one_per_thread": _dedup_max(fh, "story_id"),
        "one_per_author": _dedup_max(fh, "author"),
    }
    for alt in ("para1", "para2"):
        rid = (para_runs or {}).get(alt)
        if rid and version:
            counts = _para_counts(rid, version, resolve=resolve)
            if counts:
                scores[alt] = counts
    main_scores = fh.groupby(fh["card"].astype(object))["weight"].sum().to_dict()
    main_ranks = _ranks(main_scores, cards)
    union: set = set()
    alt_ranks = {}
    for alt, sc in scores.items():
        union |= _top(sc, cards)
        alt_ranks[alt] = _ranks(sc, cards)
    rows = [
        {
            "card": c,
            "main_rank": int(main_ranks[c]),
            "alt_ranks": {
                alt: int(alt_ranks[alt][c]) for alt in sorted(alt_ranks)
            },
        }
        for c in sorted(union, key=lambda c: (main_ranks[c], c))
    ]
    return rows

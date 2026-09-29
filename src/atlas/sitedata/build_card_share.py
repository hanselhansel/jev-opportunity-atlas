"""``card_share`` rows: the share of firsthand problems in each need group and
card, the headline numbers for the X thread.

The estimand is the phase-2-weighted share ``sum(w * 1[assigned to x]) /
sum(w)`` over firsthand problems in a population and bucket. A firsthand
problem is a phase-2 row whose facets account_type choice is
``firsthand_account``; ``weight`` is w1 / p2. An item counts as assigned to a
card when its card_id is in the cardset and card_p >= 0.5; a group row counts
the items assigned to any of its cards. "none" (and low-confidence or
non-cardset) assignments stay in the denominator.

``screen_positive`` uses pos-phase rows only. ``all_firsthand`` adds the neg
check slice (few rows with very large weights) as a sensitivity check, never
the headline. Buckets are ``all``, ``H1`` (P01-P06), ``H2`` (P07-P12), and
``H2_minus_H1``. Intervals come from a stratified thread bootstrap over
(phase-2 stratum, story_id) pairs; the difference reuses one set of draws for
both halves, and ``p_adj`` is the bootstrap two-sided p-value, BH-adjusted per
(level, population) family.
"""

from __future__ import annotations

import math

import numpy as np

from atlas.estimation.robust import bootstrap_pvalue
from atlas.sitedata.build_share import FIRSTHAND, boot_ratio, boot_totals

QUALIFIER = "as classified by Jev; assignment audited"
POPULATIONS = (("screen_positive", ("pos",)), ("all_firsthand", ("pos", "neg")))
MIN_CARD_P = 0.5
_H1 = frozenset(f"P{i:02d}" for i in range(1, 7))
_H2 = frozenset(f"P{i:02d}" for i in range(7, 13))


def _half(period) -> str | None:
    if period in _H1:
        return "H1"
    if period in _H2:
        return "H2"
    return None


def _items(ctx, cs, phases) -> list[dict]:
    """Firsthand problems in ``phases`` with their resolved card/group."""
    items = []
    for cid, f in ctx["facet"].items():
        if f.get("phase") not in phases:
            continue
        by_q = ctx["answers"].get(cid) or {}
        if (by_q.get("account_type") or {}).get("choice") != FIRSTHAND:
            continue
        c = ctx["comments"].get(cid, {})
        a = ctx["assign"].get(cid) or {}
        card = a.get("card_id")
        if (
            card in (None, "none")
            or card not in cs.all_cards
            or (a.get("card_p") or 0.0) < MIN_CARD_P
        ):
            card = None
        items.append(
            {
                "comment_id": cid,
                "story_id": f.get("story_id"),
                "stratum": f.get("stratum"),
                "weight": float(f.get("weight") or 0.0),
                "period": c.get("period"),
                "author": c.get("author"),
                "card": card,
                "group": cs.all_cards[card].group_id if card else None,
            }
        )
    return items


def _n_authors(items, ids, key) -> np.ndarray:
    return np.array(
        [
            len({r["author"] for r in items if r[key] == x and r["author"]})
            for x in ids
        ],
        dtype=int,
    )


def _share_block(items, ids, key, n_boot, seed):
    """(share, lo, hi, n_items, n_authors) per id over ``items``."""
    j = len(ids)
    ind = (
        np.array([[float(r[key] == x) for x in ids] for r in items])
        .reshape(len(items), j)
    )
    n_items = ind.sum(axis=0).astype(int)
    n_auth = _n_authors(items, ids, key)
    w = np.array([r["weight"] for r in items], dtype=float)
    share = np.full(j, np.nan)
    lo = np.full(j, np.nan)
    hi = np.full(j, np.nan)
    if items and w.sum() > 0:
        share = (w @ ind) / w.sum()
        blo, bhi = boot_ratio(
            np.ones(len(items)),
            ind,
            w,
            [r["stratum"] for r in items],
            [r["story_id"] for r in items],
            n_boot,
            seed,
        )
        lo, hi = blo, bhi
    return share, lo, hi, n_items, n_auth


def _diff_block(items, ids, key, n_boot, seed):
    """(diff, lo, hi, raw_p, n_items, n_authors) for H2 - H1 per id.

    One joint bootstrap over (stratum, thread) pairs in both halves: each
    replicate resamples the H1 and H2 totals from the same draws.
    """
    j = len(ids)
    halves = [r for r in items if _half(r["period"]) is not None]
    ind = (
        np.array([[float(r[key] == x) for x in ids] for r in halves])
        .reshape(len(halves), j)
    )
    n_items = ind.sum(axis=0).astype(int)
    n_auth = _n_authors(halves, ids, key)
    diff = np.full(j, np.nan)
    lo = np.full(j, np.nan)
    hi = np.full(j, np.nan)
    p = np.full(j, np.nan)
    w = np.array([r["weight"] for r in halves], dtype=float)
    h1 = np.array([float(_half(r["period"]) == "H1") for r in halves])
    h2 = 1.0 - h1
    if halves and w.sum() > 0:
        cols = np.column_stack(
            [
                w * h1,
                w * h2,
                w[:, None] * h1[:, None] * ind,
                w[:, None] * h2[:, None] * ind,
            ]
        )
        reps_t = boot_totals(
            cols,
            [r["stratum"] for r in halves],
            [r["story_id"] for r in halves],
            n_boot,
            seed,
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            r1 = reps_t[:, 2 : 2 + j] / reps_t[:, [0]]
            r2 = reps_t[:, 2 + j :] / reps_t[:, [1]]
        reps = r2 - r1
        den1, den2 = float((w * h1).sum()), float((w * h2).sum())
        if den1 > 0 and den2 > 0:
            s1 = (w * h1) @ ind / den1
            s2 = (w * h2) @ ind / den2
            diff = s2 - s1
            lo, hi = np.nanquantile(reps, [0.025, 0.975], axis=0)
            p = np.array([bootstrap_pvalue(reps[:, k]) for k in range(j)])
    return diff, lo, hi, p, n_items, n_auth


def _bh_adjust(pvalues: np.ndarray) -> np.ndarray:
    """BH step-up adjusted p-values: the smallest q at which
    ``atlas.estimation.robust.benjamini_hochberg`` would reject each row."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p, kind="stable")
    ranked = p[order] * m / np.arange(1, m + 1)
    adj_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.clip(adj_sorted, 0.0, 1.0)
    return out


def _f(x):
    return float(x) if x is not None and math.isfinite(x) else None


def card_share_rows(ctx, cs, n_boot=2000, seed=0) -> list[dict]:
    """One row per (population, level, id, bucket)."""
    rows = []
    for pop_name, phases in POPULATIONS:
        items = _items(ctx, cs, phases)
        for level, ids in (
            ("group", sorted(cs.groups)),
            ("card", sorted(cs.all_cards)),
        ):
            if not ids:
                continue
            labels = {
                x: (cs.groups[x] if level == "group" else cs.all_cards[x].statement)
                for x in ids
            }
            key = "group" if level == "group" else "card"
            blocks = {}
            for b in ("all", "H1", "H2"):
                sub = (
                    items
                    if b == "all"
                    else [r for r in items if _half(r["period"]) == b]
                )
                blocks[b] = _share_block(sub, ids, key, n_boot, seed)
            diff, dlo, dhi, raw_p, dn_items, dn_auth = _diff_block(
                items, ids, key, n_boot, seed
            )
            finite = np.isfinite(raw_p)
            adj = np.full(len(ids), np.nan)
            if finite.any():
                adj[finite] = _bh_adjust(raw_p[finite])
            for i, x in enumerate(ids):
                for b in ("all", "H1", "H2"):
                    share, lo, hi, n_items, n_auth = blocks[b]
                    rows.append(
                        {
                            "level": level,
                            "id": x,
                            "label": labels[x],
                            "population": pop_name,
                            "bucket": b,
                            "share": _f(share[i]),
                            "lo": _f(lo[i]),
                            "hi": _f(hi[i]),
                            "n_items": int(n_items[i]),
                            "n_authors": int(n_auth[i]),
                            "p_adj": None,
                            "qualifier": QUALIFIER,
                        }
                    )
                rows.append(
                    {
                        "level": level,
                        "id": x,
                        "label": labels[x],
                        "population": pop_name,
                        "bucket": "H2_minus_H1",
                        "share": _f(diff[i]),
                        "lo": _f(dlo[i]),
                        "hi": _f(dhi[i]),
                        "n_items": int(dn_items[i]),
                        "n_authors": int(dn_auth[i]),
                        "p_adj": _f(adj[i]),
                        "qualifier": QUALIFIER,
                    }
                )
    return rows

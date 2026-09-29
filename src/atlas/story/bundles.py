"""S3: merge-score edges and persistent bundles over the need cards.

The merge run's ``expected`` scores (a 0..2 same-problem scale) become
distances ``2 - expected``; average-linkage clustering over all cards is cut
at 0.6, 0.8, and 1.0. Bundles are the 0.8-cut clusters of 3 to 12 cards;
``persistence`` is the share of the other two cuts where the same card set
(Jaccard >= 0.7) still exists. ``edges`` keeps each card's 8 highest merge
scores at ``expected >= 1.0``, deduplicated as undirected pairs.
"""

from __future__ import annotations

import math

import numpy as np

from atlas.story import io

CUT = 0.8
OTHER_CUTS = (0.6, 1.0)
MAX_DISTANCE = 2.0
EDGE_MIN_SCORE = 1.0
EDGE_TOP = 8
MIN_BUNDLE = 3
MAX_BUNDLE = 12
JACCARD_MIN = 0.7


def _scored_pairs(merge_json, ids: set) -> dict[tuple[str, str], float]:
    """Undirected ``{card_a, card_b} -> expected`` for finite scored rows."""
    out = {}
    for s in (merge_json or {}).get("scored") or []:
        a, b, e = s.get("card_a"), s.get("card_b"), s.get("expected")
        if (
            a in ids
            and b in ids
            and a != b
            and isinstance(e, (int, float))
            and math.isfinite(e)
        ):
            key = (a, b) if a < b else (b, a)
            out[key] = max(out.get(key, -math.inf), float(e))
    return out


def _edges(scored: dict[tuple[str, str], float], ids) -> list[dict]:
    adj = {c: [] for c in ids}
    for (a, b), e in scored.items():
        adj[a].append((b, e))
        adj[b].append((a, e))
    keep = set()
    for c in ids:
        for other, e in sorted(adj[c], key=lambda t: (-t[1], t[0]))[:EDGE_TOP]:
            if e >= EDGE_MIN_SCORE:
                keep.add((c, other) if c < other else (other, c))
    return [
        {"a": a, "b": b, "score": scored[(a, b)]}
        for a, b in sorted(keep, key=lambda p: (-scored[p], p[0], p[1]))
    ]


def _clusters(labels, ids) -> list[set]:
    out: dict[int, set] = {}
    for cid, lab in zip(ids, labels):
        out.setdefault(int(lab), set()).add(cid)
    return list(out.values())


def _jaccard(a: set, b: set) -> float:
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def _persistence(members: set, other_cuts: list[list[set]]) -> float:
    hits = sum(
        any(_jaccard(members, c) >= JACCARD_MIN for c in clusters)
        for clusters in other_cuts
    )
    return hits / len(other_cuts) if other_cuts else 0.0


def _share_est(members, meta, share_reps):
    ests = []
    for m in members:
        v = (meta[m].get("share") or {}).get("est")
        ests.append(float(v) if isinstance(v, (int, float)) else 0.0)
    est = float(sum(ests))
    n = int(sum(meta[m].get("n_problems") or 0 for m in members))
    if share_reps and all(m in share_reps for m in members):
        mats = [np.asarray(share_reps[m], dtype=float).ravel() for m in members]
        k = min(x.size for x in mats)
        if k:
            rep_sum = np.sum([x[:k] for x in mats], axis=0)
            from atlas.story.boot import summarize

            got = summarize(est, rep_sum, n)
            if got is not None:
                return got
    return io.est(est, n=n)


def build_bundles(merge_json, story, share_reps=None):
    """``(bundles, edges)`` from the merge run's scored pairs.

    ``share_reps`` maps card id to joint bootstrap replicate shares so a
    bundle's interval comes from summing replicates, not from pooling the
    member intervals.
    """
    meta = {c["id"]: c for c in (story or {}).get("cards") or []}
    ids = sorted(meta)
    scored = _scored_pairs(merge_json, set(ids))
    edges = _edges(scored, ids)
    bundles = []
    if len(ids) >= MIN_BUNDLE:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import squareform

        n = len(ids)
        pos = {c: i for i, c in enumerate(ids)}
        dist = np.full((n, n), MAX_DISTANCE)
        np.fill_diagonal(dist, 0.0)
        for (a, b), e in scored.items():
            d = min(MAX_DISTANCE, max(0.0, MAX_DISTANCE - e))
            dist[pos[a], pos[b]] = dist[pos[b], pos[a]] = d
        z = linkage(squareform(dist, checks=False), method="average")
        cuts = {
            t: _clusters(fcluster(z, t=t, criterion="distance"), ids)
            for t in (CUT, *OTHER_CUTS)
        }
        for members in cuts[CUT]:
            if not (MIN_BUNDLE <= len(members) <= MAX_BUNDLE):
                continue
            bundles.append(
                {
                    "cards": sorted(members),
                    "share": _share_est(members, meta, share_reps),
                    "groups_spanned": len(
                        {meta[m].get("group") for m in members} - {None}
                    ),
                    "persistence": _persistence(
                        members, [cuts[t] for t in OTHER_CUTS]
                    ),
                }
            )
        bundles.sort(
            key=lambda b: (-(b["share"] or {}).get("est") or 0.0, b["cards"])
        )
        bundles = [
            {"id": f"b{i + 1}", **b} for i, b in enumerate(bundles)
        ]
    return bundles, edges

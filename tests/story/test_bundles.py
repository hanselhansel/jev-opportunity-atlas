"""Task 3: merge-score edges and persistent bundles."""

import numpy as np
import pytest

from atlas.story import bundles


def _scored(pairs):
    return {
        "scored": [
            {"card_a": a, "card_b": b, "score": e, "expected": e}
            for a, b, e in pairs
        ]
    }


def _story(cards):
    return {
        "cards": [
            {
                "id": c,
                "group": g,
                "share": {"est": s, "n": n, "sparse": False},
                "n_problems": n,
            }
            for c, g, s, n in cards
        ]
    }


def _clique_story():
    cards = [
        ("c01", "g01", 0.10, 60),
        ("c02", "g01", 0.05, 60),
        ("c03", "g02", 0.03, 60),
        ("c04", "g02", 0.02, 60),
        ("c05", "g02", 0.01, 60),
        ("c06", "g03", 0.01, 60),
    ]
    return _story(cards)


def test_bundle_persistence_one_for_tight_clique():
    pairs = [
        ("c01", "c02", 2.0),
        ("c01", "c03", 2.0),
        ("c01", "c04", 2.0),
        ("c02", "c03", 2.0),
        ("c02", "c04", 2.0),
        ("c03", "c04", 2.0),
    ]
    bs, _ = bundles.build_bundles(_scored(pairs), _clique_story())
    assert len(bs) == 1
    assert set(bs[0]["cards"]) == {"c01", "c02", "c03", "c04"}
    assert bs[0]["persistence"] == 1.0
    assert bs[0]["groups_spanned"] == 2
    assert bs[0]["share"]["est"] == pytest.approx(0.20)


def test_edges_top8_threshold_dedup():
    pairs = [("c01", f"c{i:02d}", 1.0 + 0.1 * (i - 2)) for i in range(2, 13)]
    pairs += [("c01", "c99", 0.5), ("c02", "c03", 1.5)]
    story = _story(
        [("c01", "g01", 0.1, 60)]
        + [(f"c{i:02d}", "g02", 0.01, 60) for i in range(2, 13)]
        + [("c99", "g03", 0.01, 60)]
    )
    _, edges = bundles.build_bundles(_scored(pairs), story)
    by_pair = {(e["a"], e["b"]): e["score"] for e in edges}
    # every undirected pair is stored once, with a < b
    assert len(edges) == len(by_pair)
    assert all(e["a"] < e["b"] for e in edges)
    # c01's own top-8 neighbours (c05..c12) are all present
    for i in range(5, 13):
        assert ("c01", f"c{i:02d}") in by_pair
    # lower-ranked c01 pairs still appear via the other card's top 8
    for i in (2, 3, 4):
        assert ("c01", f"c{i:02d}") in by_pair
    # c99 at 0.5 is below the score floor in both directions
    assert ("c01", "c99") not in by_pair
    assert all(e["score"] >= 1.0 for e in edges)
    assert by_pair[("c02", "c03")] == 1.5
    assert len(edges) == 12  # 11 c01 pairs + c02-c03


def test_no_bundles_when_clusters_too_small_or_too_big():
    # a 2-clique is below the minimum size
    story = _story(
        [("c01", "g01", 0.1, 60), ("c02", "g01", 0.1, 60),
         ("c03", "g02", 0.1, 60)]
    )
    bs, edges = bundles.build_bundles(
        _scored([("c01", "c02", 2.0)]), story
    )
    assert bs == []
    assert len(edges) == 1


def test_bundle_share_uses_joint_replicates():
    story = _clique_story()
    pairs = [
        ("c01", "c02", 2.0), ("c01", "c03", 2.0), ("c02", "c03", 2.0),
        ("c01", "c04", 0.4), ("c02", "c04", 0.4), ("c03", "c04", 0.4),
    ]
    rng = np.random.default_rng(0)
    reps = {
        c["id"]: c["share"]["est"] + rng.normal(0, 0.005, 50)
        for c in story["cards"]
    }
    bs, _ = bundles.build_bundles(_scored(pairs), story, share_reps=reps)
    assert len(bs) == 1
    b = bs[0]
    assert b["share"]["est"] == pytest.approx(0.18)
    assert b["share"]["lo95"] < b["share"]["est"] < b["share"]["hi95"]
    assert b["share"]["n"] == 180
    # c04 only links at 0.4, so it is out at the 0.8 cut
    assert "c04" not in b["cards"]


def test_missing_or_empty_merge_json():
    story = _clique_story()
    bs, edges = bundles.build_bundles({}, story)
    assert bs == [] and edges == []
    bs, edges = bundles.build_bundles(None, story)
    assert bs == [] and edges == []

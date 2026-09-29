"""Task 2: opportunity score — percentile components, presets with
renormalization over non-null parts, and bootstrap rank quantiles."""

import numpy as np
import pytest

from atlas.story import score


def _card(cid, n=60, share=None, shrunk=None, paid=None, unsolved=None,
          severe=None, ratio=None, reliability=None, customers=None):
    c = {"id": cid, "n_problems": n,
         "share": {"est": share} if share is not None else None,
         "change": {"shrunk": shrunk}}
    if paid is not None:
        c["coping"] = {"commercial": {"est": paid}}
    c["unsolved"] = (
        {"unsolved": {"est": unsolved}, "author_solved": {"est": 0.1}}
        if unsolved is not None
        else None
    )
    if severe is not None:
        c["quality"] = {"severe3": {"est": severe}}
    if ratio is not None:
        c["builders"] = {"ratio": {"est": ratio}}
    if reliability is not None or customers is not None:
        c["costs"] = {
            "reliability": {"est": reliability},
            "customers": {"est": customers},
        }
    return c


def _story(cards):
    return {"cards": cards}


def test_null_component_renormalizes():
    cards = [
        _card("cA", share=0.1, shrunk=0.01, paid=0.4, severe=0.3),
        _card("cB", share=0.2, shrunk=0.02, paid=0.3, severe=0.2, unsolved=0.5),
        _card("cC", share=0.3, shrunk=0.03, paid=0.2, severe=0.4, unsolved=0.6),
        _card("cD", share=0.4, shrunk=0.04, paid=0.1, severe=0.1, unsolved=0.7),
    ]
    cards_score, presets = score.build_scores(_story(cards), reps={})
    comp = cards_score["cA"]["components"]
    assert comp["unsolved"] is None
    manual = [v for v in comp.values() if v is not None]
    assert score.weighted_score(comp, presets["balanced"]) == pytest.approx(
        sum(manual) / len(manual)
    )
    # and it is not the naive mean with unsolved counted as zero
    assert not np.isclose(
        score.weighted_score(comp, presets["balanced"]),
        sum(manual) / len(comp),
    )


def test_all_zero_weights_equal():
    comp = {"share": 0.8, "change": 0.2, "paid": None, "unsolved": 0.4}
    zero = {k: 0 for k in score.COMPONENTS}
    expect = (0.8 + 0.2 + 0.4) / 3
    assert score.weighted_score(comp, zero) == pytest.approx(expect)
    assert score.weighted_score(comp, {}) == pytest.approx(expect)
    ones = {k: 1 for k in score.COMPONENTS}
    assert score.weighted_score(comp, ones) == pytest.approx(expect)


def test_rank_quantiles_monotone():
    rng = np.random.default_rng(0)
    cards = [
        _card(
            f"c{i:02d}",
            share=0.05 + 0.02 * i,
            shrunk=-0.02 + 0.01 * i,
            paid=0.1 + 0.05 * i,
            severe=0.2 + 0.03 * i,
        )
        for i in range(6)
    ]
    reps = {}
    for i, c in enumerate(cards):
        reps[c["id"]] = {
            "share": 0.05 + 0.02 * i + rng.normal(0, 0.01, 64),
            "change": -0.02 + 0.01 * i + rng.normal(0, 0.02, 64),
            "paid": 0.1 + 0.05 * i + rng.normal(0, 0.03, 64),
            "severity3": 0.2 + 0.03 * i + rng.normal(0, 0.03, 64),
        }
    cards_score, _ = score.build_scores(_story(cards), reps)
    qs = cards_score["c00"]["rank_quantiles"]
    assert len(qs) == 20
    assert all(isinstance(q, int) and q >= 1 for q in qs)
    assert qs == sorted(qs)


def test_thin_card_not_scored():
    cards = [
        _card("thin", n=12, share=0.5, shrunk=0.1),
        _card("fat", n=80, share=0.2, shrunk=0.0),
    ]
    cards_score, _ = score.build_scores(_story(cards), reps={})
    assert all(v is None for v in cards_score["thin"]["components"].values())
    assert cards_score["thin"]["rank_quantiles"] == []
    assert cards_score["fat"]["components"]["share"] == pytest.approx(0.5)


def test_underbuilt_is_neg_log_ratio():
    cards = [
        _card("cA", share=0.1, shrunk=0.0, ratio=0.1),
        _card("cB", share=0.2, shrunk=0.0, ratio=10.0),
    ]
    cards_score, _ = score.build_scores(_story(cards), reps={})
    # ratio 0.1 -> -log(0.1) high -> higher percentile than ratio 10
    assert (
        cards_score["cA"]["components"]["launch_ratio"]
        > cards_score["cB"]["components"]["launch_ratio"]
    )


def test_presets_cover_all_components():
    _, presets = score.build_scores(_story([_card("cA")]), reps={})
    for name in ("balanced", "growth", "paid_pain", "underbuilt"):
        assert set(presets[name]) == set(score.COMPONENTS)
        assert all(v >= 0 for v in presets[name].values())
    assert presets["growth"]["change"] == 3
    assert presets["paid_pain"]["paid"] == 3
    assert presets["underbuilt"]["launch_ratio"] == 3

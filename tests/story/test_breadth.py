"""Task 2: per-card breadth — domain mix, Chao-Shen entropy, residuals."""

import math

import pandas as pd
import pytest

from atlas.story import breadth


def _row(i, card="c1", w=1.0, domain="d1", thread=None):
    return {
        "comment_id": 9_000_000_000 + i,
        "story_id": thread if thread is not None else 9_500_000_000 + i,
        "stratum": f"s{i % 3}",
        "phase": "pos",
        "firsthand": True,
        "card": card,
        "weight": w,
        "domain": domain,
    }


def test_entropy_single_domain_zero():
    rows = [_row(i, domain="d1") for i in range(150)]
    out = breadth.card_breadth(pd.DataFrame(rows), R=50, seed=0)
    ent = out["c1"]["entropy"]
    assert ent["est"] == 0.0
    assert ent["sparse"] is False  # 150 problems >= 100


def test_entropy_uniform_max():
    rows = [
        _row(i, domain=f"d{i % 4}", thread=9_500_000_000 + i % 100)
        for i in range(4000)
    ]
    out = breadth.card_breadth(pd.DataFrame(rows), R=50, seed=0)
    ent = out["c1"]["entropy"]
    assert math.isclose(ent["est"], 2.0, abs_tol=0.1)
    assert ent["lo95"] <= ent["hi95"]
    assert ent["hi95"] - ent["lo95"] < 0.1


def test_entropy_sparse_under_100():
    rows = [_row(i, domain=f"d{i % 2}") for i in range(60)]
    out = breadth.card_breadth(pd.DataFrame(rows), R=50, seed=0)
    ent = out["c1"]["entropy"]
    assert ent["sparse"] is True
    assert math.isclose(ent["est"], 1.0, abs_tol=0.1)


def test_domains_weighted_and_residuals():
    rows = []
    # card c1: all weight in d1
    rows += [_row(i, card="c1", domain="d1", w=2.0) for i in range(50)]
    # card c2: half the population, all d2 -> c1 over-favours d1
    rows += [
        _row(1000 + i, card="c2", domain="d2", w=2.0) for i in range(50)
    ]
    out = breadth.card_breadth(pd.DataFrame(rows), R=50, seed=0)
    b1 = out["c1"]
    assert b1["domains"] == {"d1": pytest.approx(1.0)}
    assert b1["residuals"]["d1"] > 0 > b1["residuals"]["d2"]
    b2 = out["c2"]
    assert b2["domains"] == {"d2": pytest.approx(1.0)}
    assert b2["residuals"]["d2"] > 0 > b2["residuals"]["d1"]

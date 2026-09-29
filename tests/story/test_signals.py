"""Task 1: per-card coping, costs, and quality signal shares."""

import pandas as pd

from atlas.story import signals


def _row(i, card="c1", w=1.0, thread=None, **kw):
    row = {
        "comment_id": 9_000_000_000 + i,
        "story_id": thread if thread is not None else 9_500_000_000 + i,
        "stratum": "s1",
        "phase": "pos",
        "firsthand": True,
        "card": card,
        "weight": w,
        "f_paid": 0.0,
        "f_switched": 0.0,
        "f_abandoned": 0.0,
        "f_workaround": 0.0,
        "f_cost_money": 0.0,
        "f_cost_time": 0.0,
        "f_cost_reliability": 0.0,
        "f_cost_customers": 0.0,
        "severity": 0.0,
        "specificity": 0.0,
    }
    row.update(kw)
    return row


def _df(rows):
    return pd.DataFrame(rows)


def test_commercial_is_any_not_sum():
    rows = [_row(i) for i in range(40)]
    for i in range(10):
        rows[i]["f_paid"] = 0.9
        rows[i]["f_switched"] = 0.9
    out = signals.card_signals(_df(rows), R=50, seed=0)
    coping = out["c1"]["coping"]
    assert coping["paid"]["est"] == 0.25
    assert coping["switched"]["est"] == 0.25
    assert coping["commercial"]["est"] == 0.25  # not 0.5: one problem counts once


def test_thin_card_sparse():
    rows = [_row(i, f_paid=0.9, severity=3.0) for i in range(12)]
    out = signals.card_signals(_df(rows), R=50, seed=0)
    sig = out["c1"]
    for block in ("coping", "costs", "quality"):
        for name, est in sig[block].items():
            assert est["sparse"] is True, (block, name)
            assert est["n"] == 12


def test_signals_shape_and_population():
    rows = [_row(i, severity=3.0, specificity=2.6) for i in range(40)]
    rows += [
        _row(100 + i, card="c1", phase="neg") for i in range(5)
    ]
    rows += [
        _row(200 + i, card="c1", firsthand=False) for i in range(5)
    ]
    rows += [_row(300 + i, card="c2", f_workaround=0.9) for i in range(40)]
    out = signals.card_signals(_df(rows), R=50, seed=0)
    c1 = out["c1"]
    assert set(c1["coping"]) == {
        "paid", "switched", "abandoned", "workaround", "commercial"
    }
    assert set(c1["costs"]) == {"money", "time", "reliability", "customers"}
    assert set(c1["quality"]) == {"severe3", "specific3"}
    # neg-phase and non-firsthand rows are not the card's problems
    assert c1["quality"]["severe3"]["n"] == 40
    assert c1["quality"]["severe3"]["est"] == 1.0
    assert c1["quality"]["specific3"]["est"] == 1.0
    assert out["c2"]["coping"]["workaround"]["est"] == 1.0
    assert out["c2"]["coping"]["commercial"]["est"] == 0.0

"""Task 2: the joint stratified thread bootstrap (Replicates, summarize)."""

import numpy as np
import pandas as pd

from atlas.story import boot


def _frame(rows):
    return pd.DataFrame(rows)


def _toy(n_pairs=40, per=3):
    """A frame of n_pairs threads in 2 strata, per rows each, one card."""
    rows = []
    for i in range(n_pairs):
        for j in range(per):
            rows.append(
                {
                    "comment_id": i * 100 + j,
                    "story_id": 9_500_000_000 + i,
                    "stratum": f"s{i % 2}",
                    "weight": 10.0,
                    "card": "c01" if i % 3 else "c02",
                }
            )
    return _frame(rows)


def test_ratio_matches_point_estimate():
    df = _toy()
    rep = boot.Replicates(df, R=50, seed=0)
    num = (df["card"] == "c01").to_numpy(dtype=float)
    den = np.ones(len(df))
    est, reps = rep.ratio(num, den)
    w = df["weight"].to_numpy()
    assert est[0] == (w * num).sum() / (w * den).sum()
    assert reps.shape == (50, 1)


def test_same_seed_same_reps():
    df = _toy()
    a = boot.Replicates(df, R=30, seed=0)
    b = boot.Replicates(df, R=30, seed=0)
    num = (df["card"] == "c01").to_numpy(dtype=float)
    _, ra = a.ratio(num, np.ones(len(df)))
    _, rb = b.ratio(num, np.ones(len(df)))
    np.testing.assert_array_equal(ra, rb)


def test_single_thread_card_wide_interval():
    """A card packed into one thread must get a much wider interval than a
    spread card with the same n and weight."""
    rows = []
    for i in range(1200):  # background threads: the denominator population
        rows.append(
            {
                "comment_id": i * 10,
                "story_id": 9_500_000_000 + i,
                "stratum": f"s{i % 4}",
                "weight": 10.0,
                "card": "other",
            }
        )
    for j in range(80):  # card A: eighty problems in a single thread
        rows.append(
            {
                "comment_id": 9_000_009_000 + j,
                "story_id": 9_500_000_999,
                "stratum": "s0",
                "weight": 10.0,
                "card": "A",
            }
        )
    for j in range(80):  # card B: eighty problems in eighty threads
        rows.append(
            {
                "comment_id": 9_000_009_100 + j,
                "story_id": 9_500_001_100 + j,
                "stratum": f"s{j % 4}",
                "weight": 10.0,
                "card": "B",
            }
        )
    df = _frame(rows)
    rep = boot.Replicates(df, R=500, seed=0)
    num = np.column_stack(
        [(df["card"] == "A").to_numpy(float), (df["card"] == "B").to_numpy(float)]
    )
    est, reps = rep.ratio(num, np.ones(len(df)))
    wa = boot.summarize(est[0], reps[:, 0], 80)
    wb = boot.summarize(est[1], reps[:, 1], 80)
    assert wa["hi95"] - wa["lo95"] >= 5 * (wb["hi95"] - wb["lo95"])


def test_summarize_fields_and_sparse():
    reps = np.linspace(0.1, 0.2, 1000)
    e = boot.summarize(0.15, reps, 10)
    assert e["n"] == 10 and e["sparse"] is True
    assert e["lo50"] <= e["hi50"] <= e["hi95"]
    assert e["lo95"] <= e["lo50"]
    assert boot.summarize(float("nan"), reps, 10) is None
    assert boot.summarize(0.1, np.full(10, np.nan), 10) is None

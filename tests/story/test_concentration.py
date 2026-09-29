"""Task 3: per-card thread/author concentration against a null band."""

import pandas as pd
import pytest

from atlas.story import concentration

BASE, STORY = 9_000_000_000, 9_500_000_000


def _row(i, card, w=1.0, thread=None, author=None, stratum="s1"):
    return {
        "comment_id": BASE + i,
        "story_id": thread if thread is not None else STORY + i,
        "stratum": stratum,
        "phase": "pos",
        "firsthand": True,
        "card": card,
        "weight": w,
        "author": author if author is not None else f"u{i}",
    }


def _bulk(n_threads=100, per_thread=10, start=0):
    """A background card spread evenly over many threads and authors."""
    rows = []
    i = start
    for t in range(n_threads):
        for _ in range(per_thread):
            rows.append(
                _row(i, "c0", thread=STORY + 1000 + t, author=f"b{i}")
            )
            i += 1
    return rows


def test_one_thread_card_flagged():
    rows = _bulk()
    # 32 of card c1's 40 problems sit in one thread
    for i in range(32):
        rows.append(
            _row(5000 + i, "c1", thread=STORY + 2000, author=f"c{i}")
        )
    for i in range(8):
        rows.append(
            _row(6000 + i, "c1", thread=STORY + 3000 + i, author=f"d{i}")
        )
    out = concentration.card_concentration(
        pd.DataFrame(rows), sims=200, seed=0
    )
    c1 = out["c1"]
    assert c1["top3_threads"] == pytest.approx(34 / 40)
    assert c1["null_threads"][0] <= c1["null_threads"][1]
    assert c1["flagged"] is True


def test_spread_card_not_flagged():
    rows = _bulk()
    # c2's 60 problems spread one per thread over 60 distinct threads
    for i in range(60):
        rows.append(
            _row(7000 + i, "c2", thread=STORY + 4000 + i, author=f"e{i}")
        )
    out = concentration.card_concentration(
        pd.DataFrame(rows), sims=200, seed=0
    )
    c2 = out["c2"]
    assert c2["top3_threads"] == pytest.approx(3 / 60)
    assert c2["top3_authors"] == pytest.approx(3 / 60)
    assert c2["flagged"] is False
    assert 0 <= c2["null_threads"][0] <= c2["null_threads"][1] <= 1


def test_output_shape_and_empty_card():
    rows = _bulk()
    out = concentration.card_concentration(
        pd.DataFrame(rows), sims=50, seed=0
    )
    c0 = out["c0"]
    assert set(c0) == {
        "top3_threads", "top3_authors",
        "null_threads", "null_authors", "flagged",
    }
    assert c0["flagged"] is False

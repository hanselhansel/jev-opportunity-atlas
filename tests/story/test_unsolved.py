"""Task 1: the replies join — cards without enough measured problems get None,
never a share treated as zero."""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.cards.replies import UNSOLVED
from atlas.story import unsolved

BASE = 9_000_000_000


def _frame(card_rows):
    """card_rows: list of (card, n_rows, weight) -> a firsthand pos frame."""
    rows = []
    cid = BASE
    for card, n, w in card_rows:
        for i in range(n):
            rows.append(
                {
                    "comment_id": cid,
                    "story_id": cid,  # one pair per row: deterministic reps
                    "stratum": f"s{cid}",
                    "phase": "pos",
                    "firsthand": True,
                    "card": card,
                    "weight": w,
                }
            )
            cid += 1
    return pd.DataFrame(rows)


def _replies(tmp_path, rows):
    path = tmp_path / "unsolved_by_problem.parquet"
    table_rows = [
        {
            "comment_id": cid,
            "n_replies": 1,
            "any_solution_named": not uns,
            "solution_kinds": [],
            "author_says_solved": author,
            "unsolved": uns,
            "solved_p": 0.0 if uns else 1.0,
        }
        for cid, uns, author in rows
    ]
    pq.write_table(pa.Table.from_pylist(table_rows, schema=UNSOLVED), path)
    return path


def test_card_without_replies_is_none(tmp_path):
    # c01 has 35 problems but replies for only 10 (< 30): below the gate.
    fr = _frame([("c01", 35, 1.0), ("c02", 35, 1.0)])
    replies = _replies(
        tmp_path,
        [(BASE + i, True, None) for i in range(10)]
        + [(BASE + 35 + i, i % 2 == 0, None) for i in range(35)],
    )
    out = unsolved.card_unsolved(fr, replies)
    assert out["c01"] is None
    assert out["c02"] is not None
    assert out["c02"]["unsolved"]["n"] == 35


def test_unsolved_weighted(tmp_path):
    # weights 3 and 1; the weight-3 problem is unsolved -> 0.75.
    fr = _frame([("c01", 1, 3.0), ("c01", 1, 1.0)])
    replies = _replies(
        tmp_path,
        [(BASE, True, "still_unsolved"), (BASE + 1, False, "solved")],
    )
    out = unsolved.card_unsolved(fr, replies, min_answered=1)
    assert out["c01"]["unsolved"]["est"] == pytest.approx(0.75)
    assert out["c01"]["author_solved"]["est"] == pytest.approx(0.25)


def test_neg_firsthand_rows_never_count(tmp_path):
    # A neg-phase firsthand row with replies must not join the population.
    fr = _frame([("c01", 30, 1.0)])
    extra = pd.DataFrame(
        [
            {
                "comment_id": BASE + 500,
                "story_id": BASE + 500,
                "stratum": "sneg",
                "phase": "neg",
                "firsthand": True,
                "card": "c01",
                "weight": 50.0,
            }
        ]
    )
    fr = pd.concat([fr, extra], ignore_index=True)
    replies = _replies(
        tmp_path,
        [(BASE + i, True, None) for i in range(30)]
        + [(BASE + 500, False, "solved")],
    )
    out = unsolved.card_unsolved(fr, replies)
    assert out["c01"]["unsolved"]["est"] == pytest.approx(1.0)
    assert out["c01"]["author_solved"]["est"] == pytest.approx(0.0)
    assert out["c01"]["unsolved"]["n"] == 30

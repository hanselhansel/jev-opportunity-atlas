"""Per-card evidence metrics over synthetic sampled comments."""

import pyarrow as pa
import pytest

from atlas.cards.metrics import NON_FACET_VALUES, card_comments, card_metrics

BASE = 9_000_000_000
S1, S2, S3, S4 = BASE + 101, BASE + 102, BASE + 103, BASE + 104


def comments_table(rows):
    return pa.table(
        {
            "id": pa.array([r[0] for r in rows], type=pa.int64()),
            "author": pa.array([r[1] for r in rows], type=pa.string()),
            "story_id": pa.array([r[2] for r in rows], type=pa.int64()),
            "period": pa.array([r[3] for r in rows], type=pa.string()),
        }
    )


def assignments_table(rows):
    return pa.table(
        {
            "comment_id": pa.array([r[0] for r in rows], type=pa.int64()),
            "card_id": pa.array([r[1] for r in rows], type=pa.string()),
            "card_p": pa.array([r[2] for r in rows], type=pa.float64()),
        }
    )


def answers_table(rows):
    return pa.table(
        {
            "comment_id": pa.array([r[0] for r in rows], type=pa.int64()),
            "question_id": pa.array([r[1] for r in rows], type=pa.string()),
            "noul": pa.array([r[2] for r in rows], type=pa.float64()),
            "choice": pa.array([r[3] for r in rows], type=pa.string()),
            "score": pa.array([r[4] for r in rows], type=pa.float64()),
        }
    )


def sample_table(rows):
    return pa.table(
        {
            "comment_id": pa.array([r[0] for r in rows], type=pa.int64()),
            "weight": pa.array([r[1] for r in rows], type=pa.float64()),
        }
    )


def replies_table(rows):
    return pa.table(
        {
            "comment_id": pa.array([r[0] for r in rows], type=pa.int64()),
            "solved_p": pa.array([r[1] for r in rows], type=pa.float64()),
        }
    )


def fixture():
    """Card c0001: 6 comments, authors u1(x3)/u2/u3/u4, threads s1(x3)/s2(x2)/s3."""
    comments = comments_table(
        [
            (BASE + 1, "u1", S1, "P03"),
            (BASE + 2, "u1", S1, "P03"),
            (BASE + 3, "u1", S1, "P09"),
            (BASE + 4, "u2", S2, "P03"),
            (BASE + 5, "u3", S2, "P09"),
            (BASE + 6, "u4", S3, "P09"),
            (BASE + 7, "u5", S4, "P01"),  # excluded: card_p below threshold
            (BASE + 8, "u6", S4, "P01"),  # excluded: card_id "none"
            (BASE + 9, "u7", S4, "P01"),  # excluded: card_id null
            (BASE + 10, "u8", S4, "P01"),  # excluded: no assignment row
            (BASE + 11, "u9", S4, "P02"),  # card c0002, single comment
        ]
    )
    assignments = assignments_table(
        [
            (BASE + 1, "c0001", 0.9),
            (BASE + 2, "c0001", 0.8),
            (BASE + 3, "c0001", 0.7),
            (BASE + 4, "c0001", 0.6),
            (BASE + 5, "c0001", 0.55),
            (BASE + 6, "c0001", 0.5),
            (BASE + 7, "c0001", 0.4),
            (BASE + 8, "none", 0.9),
            (BASE + 9, None, 0.9),
            (BASE + 11, "c0002", 0.9),
        ]
    )
    n = None
    answers = answers_table(
        [
            (BASE + 1, "workaround", 0.9, n, n),
            (BASE + 2, "workaround", 0.6, n, n),
            (BASE + 3, "workaround", 0.4, n, n),
            (BASE + 4, "workaround", n, n, n),  # null answer, not counted
            (BASE + 1, "paid", 0.8, n, n),
            (BASE + 2, "paid", 0.7, n, n),
            (BASE + 1, "switched", 0.2, n, n),
            (BASE + 1, "resolution", n, "unresolved", n),
            (BASE + 2, "resolution", n, "resolved", n),
            (BASE + 3, "resolution", n, "unclear", n),
            (BASE + 1, "domain", n, "software_development", n),
            (BASE + 2, "domain", n, "data_ml_ai", n),
            (BASE + 3, "domain", n, "unclear", n),
            (BASE + 4, "domain", n, "other", n),
            (BASE + 1, "user_role", n, "software_engineer", n),
            (BASE + 2, "user_role", n, "founder_executive", n),
            (BASE + 3, "user_role", n, "software_engineer", n),
            (BASE + 4, "user_role", n, "mixed", n),
            (BASE + 1, "specificity", n, n, 2.0),
            (BASE + 2, "specificity", n, n, 4.0),
        ]
    )
    sample = sample_table([(BASE + i, 2.0) for i in range(1, 6)])
    replies = replies_table([(BASE + 1, 0.9), (BASE + 2, 0.3), (BASE + 2, 0.4)])
    return assignments, answers, comments, sample, replies


def row(table, card_id):
    idx = table["card_id"].to_pylist().index(card_id)
    return {name: table[name][idx].as_py() for name in table.column_names}


def test_card_comments_filters_and_weights():
    assignments, _answers, comments, sample, _replies = fixture()
    cc = card_comments(assignments, comments, sample=sample)
    assert cc.column_names == [
        "comment_id",
        "card_id",
        "author",
        "story_id",
        "period",
        "weight",
    ]
    ids = cc["comment_id"].to_pylist()
    assert sorted(ids) == [BASE + i for i in range(1, 7)] + [BASE + 11]
    weights = dict(zip(ids, cc["weight"].to_pylist()))
    assert weights[BASE + 1] == 2.0
    assert weights[BASE + 6] is None
    cc_min = card_comments(assignments, comments, min_card_p=0.4)
    assert BASE + 7 in cc_min["comment_id"].to_pylist()
    assert cc_min["weight"].to_pylist() == [None] * cc_min.num_rows


def test_counts_shares_and_periods():
    assignments, answers, comments, sample, _replies = fixture()
    m = card_metrics(assignments, answers, comments, sample, author_cap=2)
    assert m.num_rows == 2
    assert m.column_names == [
        "card_id",
        "n_comments",
        "n_comments_capped",
        "n_authors",
        "n_threads",
        "n_periods",
        "n_halfyears",
        "n_domains",
        "n_roles",
        "max_thread_share",
        "max_author_share",
        "workaround_rate",
        "paid_rate",
        "switched_rate",
        "abandoned_rate",
        "commercial_rate",
        "unresolved_rate",
        "unsolved_rate",
        "mean_specificity",
        "weighted_n",
        "first_period",
        "last_period",
    ]
    r = row(m, "c0001")
    assert r["n_comments"] == 6
    assert r["n_comments_capped"] == 5  # u1 capped at 2: 2+1+1+1
    assert r["n_authors"] == 4
    assert r["n_threads"] == 3
    assert r["n_periods"] == 2
    assert r["n_halfyears"] == 2  # P03 -> H1, P09 -> H2
    assert r["n_domains"] == 2
    assert r["n_roles"] == 2
    assert r["max_thread_share"] == pytest.approx(0.5)
    assert r["max_author_share"] == pytest.approx(0.5)
    assert r["first_period"] == "P03"
    assert r["last_period"] == "P09"
    assert r["weighted_n"] == pytest.approx(10.0)
    r2 = row(m, "c0002")
    assert r2["n_comments"] == 1
    assert r2["n_authors"] == 1
    assert r2["weighted_n"] == 0.0  # no sample row


def test_rates_and_thresholds():
    assignments, answers, comments, sample, _replies = fixture()
    m = card_metrics(assignments, answers, comments, sample)
    r = row(m, "c0001")
    assert r["workaround_rate"] == pytest.approx(2 / 3)
    assert r["paid_rate"] == pytest.approx(1.0)
    assert r["switched_rate"] == pytest.approx(0.0)
    assert r["abandoned_rate"] is None
    assert r["commercial_rate"] == pytest.approx(1.0)
    assert r["unresolved_rate"] == pytest.approx(1 / 3)
    assert r["mean_specificity"] == pytest.approx(3.0)
    m2 = card_metrics(
        assignments, answers, comments, sample, thresholds={"workaround": 0.95}
    )
    assert row(m2, "c0001")["workaround_rate"] == pytest.approx(0.0)


def test_unsolved_rate():
    assignments, answers, comments, sample, replies = fixture()
    m = card_metrics(assignments, answers, comments, sample)
    assert row(m, "c0001")["unsolved_rate"] is None
    m2 = card_metrics(assignments, answers, comments, sample, replies=replies)
    # c1 solved (0.9), c2 unsolved (0.3, 0.4): 1 of 2 comments with replies
    assert row(m2, "c0001")["unsolved_rate"] == pytest.approx(0.5)
    assert row(m2, "c0002")["unsolved_rate"] is None


def test_duplicate_answers_raise():
    assignments, _answers, comments, sample, _replies = fixture()
    n = None
    dup = answers_table(
        [(BASE + 1, "paid", 0.5, n, n), (BASE + 1, "paid", 0.6, n, n)]
    )
    with pytest.raises(ValueError, match="duplicate"):
        card_metrics(assignments, dup, comments, sample)


def test_non_facet_values_excluded():
    assert set(NON_FACET_VALUES) >= {"other", "mixed", "unclear"}

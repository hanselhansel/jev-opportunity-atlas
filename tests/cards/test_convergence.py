"""Convergence: problem x domain x role matrices and effective-category index."""

import math

import pyarrow as pa
import pytest

from atlas.cards.convergence import (
    convergence,
    convergence_index,
    problem_domain_matrix,
    problem_role_matrix,
)

BASE = 9_000_000_000


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
    n = None
    return pa.table(
        {
            "comment_id": pa.array([r[0] for r in rows], type=pa.int64()),
            "question_id": pa.array([r[1] for r in rows], type=pa.string()),
            "choice": pa.array([r[2] for r in rows], type=pa.string()),
            "noul": pa.array([n] * len(rows), type=pa.float64()),
            "score": pa.array([n] * len(rows), type=pa.float64()),
        }
    )


def fixture():
    """c0001: domains sw_dev{u1,u2} + data_ml{u3}; roles eng{u1,u2,u3}, founder{u4}.

    c0002: 4 domains x 4 authors (even), all software_engineer role.
    c0003: one comment, no facet answers.
    """
    comments = comments_table(
        [(BASE + i, f"u{i}", BASE + 100 + i, "P01") for i in range(1, 13)]
    )
    assignments = assignments_table(
        [(BASE + i, "c0001", 0.9) for i in range(1, 6)]
        + [(BASE + i, "c0002", 0.9) for i in range(6, 10)]
        + [(BASE + 12, "c0003", 0.9)]
    )
    answers = answers_table(
        [
            (BASE + 1, "domain", "software_development"),
            (BASE + 2, "domain", "software_development"),
            (BASE + 3, "domain", "data_ml_ai"),
            (BASE + 4, "domain", "unclear"),
            (BASE + 5, "domain", "other"),
            (BASE + 1, "user_role", "software_engineer"),
            (BASE + 2, "user_role", "software_engineer"),
            (BASE + 3, "user_role", "software_engineer"),
            (BASE + 4, "user_role", "founder_executive"),
            (BASE + 5, "user_role", "mixed"),
            (BASE + 6, "domain", "security_privacy"),
            (BASE + 7, "domain", "finance_payments"),
            (BASE + 8, "domain", "health_medical"),
            (BASE + 9, "domain", "education_learning"),
            (BASE + 6, "user_role", "software_engineer"),
            (BASE + 7, "user_role", "software_engineer"),
            (BASE + 8, "user_role", "software_engineer"),
            (BASE + 9, "user_role", "software_engineer"),
        ]
    )
    return assignments, answers, comments


def test_problem_domain_matrix():
    assignments, answers, comments = fixture()
    m = problem_domain_matrix(assignments, answers, comments)
    assert m.column_names == ["card_id", "domain", "n_authors"]
    rows = sorted(m.to_pylist(), key=lambda r: (r["card_id"], r["domain"]))
    assert rows == [
        {"card_id": "c0001", "domain": "data_ml_ai", "n_authors": 1},
        {"card_id": "c0001", "domain": "software_development", "n_authors": 2},
        {"card_id": "c0002", "domain": "education_learning", "n_authors": 1},
        {"card_id": "c0002", "domain": "finance_payments", "n_authors": 1},
        {"card_id": "c0002", "domain": "health_medical", "n_authors": 1},
        {"card_id": "c0002", "domain": "security_privacy", "n_authors": 1},
    ]


def test_problem_role_matrix():
    assignments, answers, comments = fixture()
    m = problem_role_matrix(assignments, answers, comments)
    assert m.column_names == ["card_id", "role", "n_authors"]
    rows = sorted(m.to_pylist(), key=lambda r: (r["card_id"], r["role"]))
    assert rows == [
        {"card_id": "c0001", "role": "founder_executive", "n_authors": 1},
        {"card_id": "c0001", "role": "software_engineer", "n_authors": 3},
        {"card_id": "c0002", "role": "software_engineer", "n_authors": 4},
    ]


def test_convergence_index_values():
    assert convergence_index([]) == 0.0
    assert convergence_index([0, 0]) == 0.0
    assert convergence_index([4]) == pytest.approx(1.0)
    assert convergence_index([1, 1, 1, 1]) == pytest.approx(4.0)
    # entropy of (2,1,1): 0.5 ln2 + 0.5 ln4 -> exp = 2*sqrt(2); zeros ignored
    expected = math.exp(-(0.5 * math.log(0.5) + 0.5 * math.log(0.25)))
    assert convergence_index([2, 1, 1]) == pytest.approx(expected)
    assert convergence_index([2, 0, 1, 1]) == pytest.approx(expected)
    assert convergence_index({"a": 2, "b": 1, "c": 1}) == pytest.approx(expected)


def test_convergence_table():
    assignments, answers, comments = fixture()
    t = convergence(assignments, answers, comments)
    assert t.column_names == ["card_id", "effective_domains", "effective_roles"]
    rows = {r["card_id"]: r for r in t.to_pylist()}
    assert set(rows) == {"c0001", "c0002", "c0003"}
    assert rows["c0001"]["effective_domains"] == pytest.approx(
        convergence_index([2, 1])
    )
    assert rows["c0001"]["effective_roles"] == pytest.approx(
        convergence_index([3, 1])
    )
    assert rows["c0002"]["effective_domains"] == pytest.approx(4.0)
    assert rows["c0002"]["effective_roles"] == pytest.approx(1.0)
    assert rows["c0003"]["effective_domains"] == 0.0
    assert rows["c0003"]["effective_roles"] == 0.0

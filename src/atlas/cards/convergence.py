"""Convergence: how a need card's evidence spreads across domains and roles.

The matrices count distinct authors per (card, category) cell; the convergence
index is the effective number of categories (exp of Shannon entropy). These are
discovery metrics over sampled, assigned comments, not population prevalence;
population claims use ``atlas.estimation`` (L12).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import pyarrow as pa

from atlas.cards.metrics import NON_FACET_VALUES, card_comments


def _category_matrix(
    assignments, answers, comments, question_id, category_col, min_card_p
) -> pa.Table:
    """Long table (card_id, <category_col>, n_authors) over assigned comments."""
    import duckdb

    non_facet = ", ".join(f"'{v}'" for v in NON_FACET_VALUES)
    cc = card_comments(assignments, comments, min_card_p=min_card_p)
    con = duckdb.connect()
    try:
        con.register("cc", cc)
        con.register("answers", answers)
        return con.execute(
            f"""
            select cc.card_id, a.choice as {category_col},
                count(distinct cc.author) as n_authors
            from cc
            join answers a on a.comment_id = cc.comment_id
            where a.question_id = '{question_id}'
                and cc.author is not null
                and a.choice is not null
                and a.choice not in ({non_facet})
            group by 1, 2
            order by 1, 2
            """
        ).to_arrow_table()
    finally:
        con.close()


def problem_domain_matrix(
    assignments, answers, comments, min_card_p=0.5
) -> pa.Table:
    """Distinct authors per (card_id, domain), excluding non-facet choices."""
    return _category_matrix(
        assignments, answers, comments, "domain", "domain", min_card_p
    )


def problem_role_matrix(
    assignments, answers, comments, min_card_p=0.5
) -> pa.Table:
    """Distinct authors per (card_id, role), excluding non-facet choices."""
    return _category_matrix(
        assignments, answers, comments, "user_role", "role", min_card_p
    )


def convergence_index(counts) -> float:
    """Effective number of categories: exp(Shannon entropy, natural log).

    ``counts`` is a Sequence or Mapping of non-negative numbers; zeros are
    ignored. Empty or all-zero input returns 0.0. An even distribution over
    four categories returns 4.0; a single category returns 1.0.
    """
    if isinstance(counts, Mapping):
        counts = list(counts.values())
    elif not isinstance(counts, Sequence):
        counts = list(counts)
    vals = [float(c) for c in counts if c is not None and c > 0]
    total = sum(vals)
    if total <= 0.0:
        return 0.0
    entropy = -sum((v / total) * math.log(v / total) for v in vals)
    return math.exp(entropy)


def _effective(matrix, category_col) -> pa.Table:
    """Per-card exp(entropy) of the matrix's n_authors distribution."""
    import duckdb

    con = duckdb.connect()
    try:
        con.register("m", matrix)
        return con.execute(
            f"""
            select card_id, exp(-sum(p * ln(p))) as effective_{category_col}s
            from (
                select card_id, {category_col},
                    n_authors::double
                        / sum(n_authors) over (partition by card_id) as p
                from m
            ) t
            group by card_id
            """
        ).to_arrow_table()
    finally:
        con.close()


def convergence(assignments, answers, comments, min_card_p=0.5) -> pa.Table:
    """Per-card (card_id, effective_domains, effective_roles), 0.0 when a card
    has no domain/role answers. One row per card in ``card_comments``."""
    import duckdb

    cc = card_comments(assignments, comments, min_card_p=min_card_p)
    dom = problem_domain_matrix(assignments, answers, comments, min_card_p)
    rol = problem_role_matrix(assignments, answers, comments, min_card_p)
    con = duckdb.connect()
    try:
        con.register("cc", cc)
        con.register("dom", _effective(dom, "domain"))
        con.register("rol", _effective(rol, "role"))
        return con.execute(
            """
            select cards.card_id,
                coalesce(dom.effective_domains, 0.0) as effective_domains,
                coalesce(rol.effective_roles, 0.0) as effective_roles
            from (select distinct card_id from cc) cards
            left join dom on dom.card_id = cards.card_id
            left join rol on rol.card_id = cards.card_id
            order by cards.card_id
            """
        ).to_arrow_table()
    finally:
        con.close()

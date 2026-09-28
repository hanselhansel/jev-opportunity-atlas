"""Per-card evidence metrics over sampled, assigned comments.

These are discovery metrics: sample counts and rates over the comments that were
drawn, answered, and assigned to a need card. They are not population
prevalence; population claims use ``atlas.estimation`` (L12).
"""

from __future__ import annotations

import pyarrow as pa

# Choice values that carry no domain/role signal; excluded (with nulls) when
# counting distinct domains and roles in metrics and convergence.
NON_FACET_VALUES = ("other", "mixed", "unclear")

_NOUL_FACETS = ("workaround", "paid", "switched", "abandoned")
_CHOICE_FACETS = ("domain", "user_role", "resolution")


def card_comments(assignments, comments, sample=None, min_card_p=0.5) -> pa.Table:
    """Assigned comments joined to comment metadata (and sample weights).

    Keeps assignment rows whose ``card_id`` is not null, is not ``"none"``, and
    whose ``card_p`` >= ``min_card_p``, inner-joined to ``comments`` on
    ``comment_id = comments.id``. When ``sample`` is given, ``weight`` is
    left-joined on ``comment_id`` (null when not sampled); otherwise all null.
    Columns: comment_id, card_id, author, story_id, period, weight.
    """
    import duckdb

    con = duckdb.connect()
    try:
        con.register("assignments", assignments)
        con.register("comments", comments)
        if sample is not None:
            con.register("sample", sample)
            weight = "s.weight"
            join = "left join sample s on s.comment_id = a.comment_id"
        else:
            weight = "cast(null as double)"
            join = ""
        return con.execute(
            f"""
            select a.comment_id, a.card_id, c.author, c.story_id, c.period,
                {weight} as weight
            from assignments a
            join comments c on c.id = a.comment_id
            {join}
            where a.card_id is not null and a.card_id <> 'none'
                and a.card_p >= {float(min_card_p)!r}
            """
        ).to_arrow_table()
    finally:
        con.close()


def card_metrics(
    assignments,
    answers,
    comments,
    sample,
    author_cap=3,
    min_card_p=0.5,
    thresholds=None,
    replies=None,
) -> pa.Table:
    """One row per card with sample counts and facet rates.

    These are discovery metrics over sampled, assigned comments, not population
    prevalence; population claims use ``atlas.estimation`` (L12).

    ``thresholds`` maps a noul facet id to its yes threshold (default 0.5).
    ``replies`` is an optional table of (comment_id, solved_p) reply rows;
    ``unsolved_rate`` is the share of card comments with at least one reply
    where no reply has ``solved_p`` >= 0.5 (null when ``replies`` is None or no
    card comment has replies). Raises ValueError on duplicate
    (comment_id, question_id) answer rows.
    """
    import duckdb

    thresholds = thresholds or {}
    thr = {f: float(thresholds.get(f, 0.5)) for f in _NOUL_FACETS}
    non_facet = ", ".join(f"'{v}'" for v in NON_FACET_VALUES)

    con = duckdb.connect()
    try:
        con.register("answers", answers)
        dup = con.execute(
            "select comment_id, question_id from answers "
            "group by 1, 2 having count(*) > 1 limit 1"
        ).fetchall()
        if dup:
            raise ValueError(
                "answers has duplicate (comment_id, question_id) rows, "
                f"e.g. {dup[0]}"
            )

        cc = card_comments(assignments, comments, sample=sample, min_card_p=min_card_p)
        con.register("cc", cc)
        if replies is not None:
            con.register("replies", replies)
            replies_cte = """
            , reply_stats as (
                select e.card_id,
                    count(r.any_solved) as replies_n,
                    count(*) filter (r.any_solved = 0) as unsolved_yes
                from enr e
                left join (
                    select comment_id,
                        max(case when solved_p >= 0.5 then 1 else 0 end) as any_solved
                    from replies group by comment_id
                ) r on r.comment_id = e.comment_id
                group by e.card_id
            )
            """
            unsolved_expr = (
                "case when rs.replies_n > 0 "
                "then rs.unsolved_yes::double / rs.replies_n end"
            )
            replies_join = "left join reply_stats rs on rs.card_id = b.card_id"
        else:
            replies_cte = ""
            unsolved_expr = "cast(null as double)"
            replies_join = ""

        noul_cols = ", ".join(
            f"max(case when question_id = '{f}' then noul end) as {f}"
            for f in _NOUL_FACETS
        )
        choice_cols = ", ".join(
            f"max(case when question_id = '{f}' then choice end) as {f}"
            for f in _CHOICE_FACETS
        )
        rate_cols = ", ".join(
            f"count({f}) as {f}_n, "
            f"count(*) filter ({f} >= {thr[f]!r}) as {f}_yes"
            for f in _NOUL_FACETS
        )
        rate_exprs = ", ".join(
            f"case when b.{f}_n > 0 then b.{f}_yes::double / b.{f}_n "
            f"end as {f}_rate"
            for f in _NOUL_FACETS
        )
        commercial = "greatest(" + ", ".join(
            f"case when b.{f}_n > 0 then b.{f}_yes::double / b.{f}_n end"
            for f in ("paid", "switched", "abandoned")
        ) + ")"

        return con.execute(
            f"""
            with noul_p as (
                select comment_id, {noul_cols}
                from answers group by comment_id
            ),
            choice_p as (
                select comment_id, {choice_cols}
                from answers group by comment_id
            ),
            score_p as (
                select comment_id, max(score) as specificity
                from answers where question_id = 'specificity'
                group by comment_id
            ),
            enr as (
                select cc.*, np.workaround, np.paid, np.switched, np.abandoned,
                    cp.domain, cp.user_role, cp.resolution, sp.specificity
                from cc
                left join noul_p np on np.comment_id = cc.comment_id
                left join choice_p cp on cp.comment_id = cc.comment_id
                left join score_p sp on sp.comment_id = cc.comment_id
            ),
            base as (
                select card_id,
                    count(*) as n_comments,
                    count(distinct author) as n_authors,
                    count(distinct story_id) as n_threads,
                    count(distinct period) as n_periods,
                    count(distinct case
                        when period between 'P01' and 'P06' then 'H1'
                        when period between 'P07' and 'P12' then 'H2'
                    end) as n_halfyears,
                    count(distinct case
                        when domain in ({non_facet}) then null else domain
                    end) as n_domains,
                    count(distinct case
                        when user_role in ({non_facet}) then null else user_role
                    end) as n_roles,
                    {rate_cols},
                    count(resolution) as resolution_n,
                    count(*) filter (resolution = 'unresolved') as unresolved_yes,
                    avg(specificity) as mean_specificity,
                    coalesce(sum(weight), 0.0) as weighted_n,
                    min(period) as first_period,
                    max(period) as last_period
                from enr group by card_id
            ),
            capped as (
                select card_id, sum(n) as n_comments_capped from (
                    select card_id, least(count(*), {int(author_cap)}) as n
                    from enr where author is not null
                    group by card_id, author
                    union all
                    select card_id, 1 from enr where author is null
                ) t group by card_id
            ),
            thread_share as (
                select ts.card_id,
                    max(ts.cnt)::double / b.n_comments as max_thread_share
                from (
                    select card_id, count(*) as cnt from enr
                    group by card_id,
                        case when story_id is null then comment_id
                            else story_id end
                ) ts
                join base b on b.card_id = ts.card_id
                group by ts.card_id, b.n_comments
            ),
            author_share as (
                select ac.card_id,
                    max(ac.cnt)::double / b.n_comments as max_author_share
                from (
                    select card_id, count(*) as cnt from enr
                    where author is not null
                    group by card_id, author
                ) ac
                join base b on b.card_id = ac.card_id
                group by ac.card_id, b.n_comments
            )
            {replies_cte}
            select b.card_id, b.n_comments, c.n_comments_capped, b.n_authors,
                b.n_threads, b.n_periods, b.n_halfyears, b.n_domains, b.n_roles,
                ts.max_thread_share, ash.max_author_share,
                {rate_exprs},
                {commercial} as commercial_rate,
                case when b.resolution_n > 0
                    then b.unresolved_yes::double / b.resolution_n
                end as unresolved_rate,
                {unsolved_expr} as unsolved_rate,
                b.mean_specificity, b.weighted_n, b.first_period, b.last_period
            from base b
            left join capped c on c.card_id = b.card_id
            left join thread_share ts on ts.card_id = b.card_id
            left join author_share ash on ash.card_id = b.card_id
            {replies_join}
            order by b.card_id
            """
        ).to_arrow_table()
    finally:
        con.close()

"""Evidence, findings, and finding_evidence rows from saved runs.

Evidence carries ids, Jev's labels and probabilities, and the text hash; never
text or authors. Findings come from ``atlas.cards`` metrics and ranking: cards
are ranked on the explore half, and a card is ``validated`` only when it meets
the pre-registered criteria (``configs/finding_criteria.toml``) in both the
explore and confirm halves. Card text is the approved cardset text, written by
Claude and approved by Hansel; Jev writes no text.
"""

from __future__ import annotations

import json

import pyarrow as pa

NONE = "none"
COST_FACETS = ("cost_time", "cost_money", "cost_reliability", "cost_customers")
SPECIFICITY_MAX = 3.0  # facets specificity has four ordered options, 0..3


def _noul(by_q: dict, qid: str):
    row = by_q.get(qid)
    return None if row is None else row.get("noul")


def _mean(values) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def evidence_rows(ids, ctx) -> list[dict]:
    """One evidence row per phase-2 ``pos`` comment id (faceted or assigned).

    The ``neg`` check slice never reaches the site, and the weight is always
    the phase-2 weight (w1 / p2), never the screen weight.
    """
    rows = []
    for cid in sorted(ids):
        f = ctx["facet"].get(cid)
        if f is None or f.get("phase") != "pos":
            continue
        c = ctx["comments"].get(cid, {})
        s = ctx["screen"].get(cid, {})
        by_q = ctx["answers"].get(cid, {})
        dom = by_q.get("domain") or {}
        costs = [_noul(by_q, q) for q in COST_FACETS]
        costs = [v for v in costs if v is not None]
        consequence = max(costs) if costs else None
        spec = (by_q.get("specificity") or {}).get("score")
        spec_n = None if spec is None else min(max(spec / SPECIFICITY_MAX, 0.0), 1.0)
        workaround = _noul(by_q, "workaround")
        a = ctx["assign"].get(cid) or {}
        card = a.get("card_id")
        model = next(
            (r.get("model_returned") for r in by_q.values() if r.get("model_returned")),
            s.get("model_returned"),
        )
        rows.append(
            {
                "comment_id": cid,
                "lane": "breadth",
                "domain": dom.get("choice"),
                "subtopic": card if card not in (None, NONE) else None,
                "period": c.get("period"),
                "story_id": c.get("story_id", s.get("story_id")),
                "thread_type": c.get("thread_type"),
                "firsthand_p": s.get("firsthand_p"),
                "account_type": (by_q.get("account_type") or {}).get("choice"),
                "specificity": spec,
                "workaround_p": workaround,
                "consequence_any_p": consequence,
                "evidence_strength": _mean(
                    [s.get("firsthand_p"), workaround, consequence, spec_n]
                ),
                "support_sentence_id": (by_q.get("pain_sentence") or {}).get("choice"),
                "model_returned": model,
                "run_id": ctx["facets_run"],
                "human_label": ctx["human"].get(cid),
                "text_sha256": c.get("text_sha256"),
                "question_set": ctx["question_set"],
                "taxonomy_version": ctx["taxonomy_version"],
                "weight": f.get("weight"),
                "confidence": dom.get("confidence"),
                "probabilities_json": dom.get("probabilities_json"),
            }
        )
    return rows


def _answers_table(answers: dict) -> pa.Table:
    rows = [
        {
            "comment_id": cid,
            "question_id": qid,
            "noul": r.get("noul"),
            "choice": r.get("choice"),
            "score": r.get("score"),
        }
        for cid, by_q in answers.items()
        for qid, r in by_q.items()
    ]
    schema = pa.schema(
        [
            ("comment_id", pa.int64()),
            ("question_id", pa.string()),
            ("noul", pa.float64()),
            ("choice", pa.string()),
            ("score", pa.float64()),
        ]
    )
    return pa.Table.from_pylist(rows, schema=schema)


def _tables(ctx, assign_rows):
    assignments = pa.Table.from_pylist(
        [
            {
                "comment_id": r["comment_id"],
                "card_id": r["card_id"],
                "card_p": r["card_p"],
                "story_id": ctx["comments"].get(r["comment_id"], {}).get("story_id"),
            }
            for r in assign_rows
        ],
        schema=pa.schema(
            [
                ("comment_id", pa.int64()),
                ("card_id", pa.string()),
                ("card_p", pa.float64()),
                ("story_id", pa.int64()),
            ]
        ),
    )
    comments = pa.Table.from_pylist(
        [
            {"id": cid, **{k: c.get(k) for k in ("author", "story_id", "period")}}
            for cid, c in ctx["comments"].items()
        ],
        schema=pa.schema(
            [
                ("id", pa.int64()),
                ("author", pa.string()),
                ("story_id", pa.int64()),
                ("period", pa.string()),
            ]
        ),
    )
    # Correct weights for faceted and assigned comments are the phase-2
    # weights (w1 / p2) on the pos phase; the screen weight w1 is wrong here.
    sample = pa.Table.from_pylist(
        [
            {"comment_id": cid, "weight": f["weight"]}
            for cid, f in ctx["facet"].items()
            if f.get("phase") == "pos"
        ],
        schema=pa.schema([("comment_id", pa.int64()), ("weight", pa.float64())]),
    )
    return assignments, _answers_table(ctx["answers"]), comments, sample


def _explore_order(explore, answers, comments, sample, weights) -> list[str]:
    from atlas.cards.convergence import convergence
    from atlas.cards.metrics import card_metrics
    from atlas.cards.rank import rank_cards, ranking_inputs

    if explore.num_rows == 0:
        return []
    m = card_metrics(explore, answers, comments, sample)
    if m.num_rows == 0:
        return []
    conv = convergence(explore, answers, comments)
    ranked = rank_cards(ranking_inputs(m, conv), weights)
    return ranked["card_id"].to_pylist()


def finding_rows(ctx, cs, criteria, weights, top_n=20, built_at=None, replies=None):
    """(findings rows, finding_evidence rows) for the top ``top_n`` cards."""
    from atlas.cards.metrics import card_comments, card_metrics
    from atlas.cards.rank import evaluate_criteria, split_by_half

    assign_rows = [
        r
        for r in ctx["assign"].values()
        if r.get("card_id") not in (None, NONE)
        and (ctx["facet"].get(r["comment_id"]) or {}).get("phase") == "pos"
    ]
    assignments, answers, comments, sample = _tables(ctx, assign_rows)
    if assignments.num_rows == 0:
        return [], []
    metrics = {
        r["card_id"]: r
        for r in card_metrics(
            assignments, answers, comments, sample, replies=replies
        ).to_pylist()
    }
    halves = split_by_half(assignments)
    gate = {
        r["card_id"]: r
        for r in evaluate_criteria(
            card_metrics(halves["explore"], answers, comments, sample),
            card_metrics(halves["confirm"], answers, comments, sample),
            criteria,
        ).to_pylist()
    }
    order = _explore_order(halves["explore"], answers, comments, sample, weights)
    order += sorted(c for c in metrics if c not in order)
    order = [c for c in order if c in metrics and c in cs.all_cards][:top_n]
    members = card_comments(assignments, comments).to_pylist()

    findings, evidence = [], []
    for cid in order:
        m, card = metrics[cid], cs.all_cards[cid]
        g = gate.get(cid) or {"candidate": False, "reasons": []}
        mine = [r for r in members if r["card_id"] == cid]
        roles = []
        for r in sorted(mine, key=lambda r: r["comment_id"]):
            verified = ctx["assign"][r["comment_id"]].get("verified_p")
            role = (
                "contradicting"
                if verified is not None and verified < 0.5
                else "supporting"
            )
            roles.append(role)
            evidence.append(
                {
                    "finding_id": cid,
                    "comment_id": r["comment_id"],
                    "match_p": ctx["assign"][r["comment_id"]].get("card_p"),
                    "role": role,
                }
            )
        n_contra = roles.count("contradicting")
        unmet = sorted({x.split(":", 1)[1].split()[0] for x in g["reasons"]})
        findings.append(
            {
                "finding_id": cid,
                "title": card.statement,
                "domain": _top_domain(mine, ctx["answers"]),
                "subtopic": cid,
                "n_comments": m["n_comments"],
                "n_threads": m["n_threads"],
                "n_authors": m["n_authors"],
                "months_present": m["n_periods"],
                "contradicting": n_contra > 0,
                "status": "validated" if g["candidate"] else "candidate",
                "lane": "breadth",
                "problem_statement": card.statement,
                "user_workflow": cs.groups.get(card.group_id),
                "workarounds_json": "[]",
                "solutions_named_json": "[]",
                "contradicting_n": n_contra,
                "unknowns_json": json.dumps(unmet),
                "discovery_question": None,
                "first_period": m["first_period"],
                "last_period": m["last_period"],
                "max_thread_share": m["max_thread_share"],
                "unsolved_rate": m.get("unsolved_rate"),
                "run_id": ctx["assign_run"],
                "question_set": ctx["question_set"],
                "taxonomy_version": ctx["taxonomy_version"],
                "validated_at": built_at if g["candidate"] else None,
            }
        )
    return findings, evidence


def _top_domain(members, answers) -> str | None:
    counts: dict[str, int] = {}
    for r in members:
        d = ((answers.get(r["comment_id"]) or {}).get("domain") or {}).get("choice")
        if d is not None:
            counts[d] = counts.get(d, 0) + 1
    return min(counts, key=lambda d: (-counts[d], d)) if counts else None

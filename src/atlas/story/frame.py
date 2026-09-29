"""The story analysis frame: one row per phase-2 sample comment.

Joins the phase-2 sample (weights, strata, phase, wave), the facets@2 answers
(account type, domain, role, yes/no facets as ``f_<qid>`` nouls, and the
severity/specificity scores), the t3 assignments (``card`` counts only at
``card_p >= 0.5`` and never ``none``), and the snapshot comments (period,
author). ``firsthand`` is the facets@2 ``firsthand_account`` choice;
``placed`` is a firsthand problem with a counted card.
"""

from __future__ import annotations

import pyarrow.parquet as pq

from atlas import paths

MIN_CARD_P = 0.5
FIRSTHAND = "firsthand_account"
CHOICE_COLS = ("account_type", "domain", "user_role")


def load_frame(
    facet_sample: str,
    facets_run: str,
    assign_run: str,
    snapshot_id: str,
    cardset: str = "main",
    version: str = "t3",
):
    """Load the phase-2 frame as a pandas DataFrame.

    ``frame.attrs["cardset"]`` carries the resolved CardSet so downstream
    builders can recover labels and statements without re-deriving them.
    """
    import pandas as pd

    from atlas.cards.engine import assign
    from atlas.inference.questions import load_question_set
    from atlas.sitedata.inputs import find_cardset

    cs = find_cardset(version, cardset)
    qs = load_question_set("facets", 2)
    noul_qs = [q for q, d in qs.questions.items() if d.get("type") == "noul"]
    score_qs = [q for q, d in qs.questions.items() if d.get("type") == "score"]
    sample = pq.read_table(paths.sample_path(facet_sample)).to_pylist()
    answers = assign.read_answers(paths.run_dir(facets_run), qs.label)
    assigned = {}
    for r in assign.load_assignments(paths.run_dir(assign_run), version).rows:
        card = r.get("card_id")
        if card in (None, "none") or card not in cs.all_cards:
            card = None
        else:
            card = cs.resolve(card)
            if (r.get("card_p") or 0.0) < MIN_CARD_P:
                card = None
        assigned[int(r["comment_id"])] = {"card": card, "card_p": r.get("card_p")}

    comments = {
        r["id"]: r
        for r in pq.read_table(
            paths.snapshot_dir(snapshot_id) / "comments.parquet",
            columns=["id", "author", "period"],
            filters=[("id", "in", list({r["comment_id"] for r in sample}))],
        ).to_pylist()
    }

    rows = []
    for r in sample:
        cid = int(r["comment_id"])
        by_q = answers.get(cid) or {}
        a = assigned.get(cid) or {}
        c = comments.get(cid, {})
        account_type = (by_q.get("account_type") or {}).get("choice")
        card = a.get("card")
        row = {
            "comment_id": cid,
            "story_id": r["story_id"],
            "stratum": r["stratum"],
            "phase": r["phase"],
            "wave": int(r.get("wave") or 1),
            "half": r.get("half"),
            "weight": float(r.get("weight") or 0.0),
            "period": c.get("period"),
            "author": c.get("author"),
            "account_type": account_type,
            "domain": (by_q.get("domain") or {}).get("choice"),
            "user_role": (by_q.get("user_role") or {}).get("choice"),
            "card": card,
            "group": cs.all_cards[card].group_id if card else None,
            "card_p": a.get("card_p"),
            "firsthand": bool(account_type == FIRSTHAND),
            "placed": bool(account_type == FIRSTHAND and card is not None),
        }
        for q in noul_qs:
            row[f"f_{q}"] = (by_q.get(q) or {}).get("noul")
        for q in score_qs:
            row[q] = (by_q.get(q) or {}).get("score")
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("comment_id").reset_index(drop=True)
    df.attrs["cardset"] = cs
    df.attrs["question_set"] = qs.label
    return df

"""Response-shape validation for Jev answers (re-exported by client)."""

from __future__ import annotations

from typing import Any


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_answers(questions: dict, body: dict) -> bool:
    """True when `body["answers"]` covers every question id with a matching type:
    noul needs a numeric `noul`; choice needs `choice` among the offered options
    and `probabilities` covering every option; score needs a numeric `score` and,
    when `probabilities` is present, one entry per criterion index."""
    if not isinstance(body, dict):
        return False
    answers = body.get("answers")
    if not isinstance(answers, dict):
        return False
    for qid, q in questions.items():
        a = answers.get(qid)
        if not isinstance(a, dict) or a.get("type") != q.get("type"):
            return False
        qtype = q.get("type")
        if qtype == "choice":
            options = list(q.get("criteria") or [])
            if a.get("choice") not in options:
                return False
            probs = a.get("probabilities")
            if not isinstance(probs, dict) or any(o not in probs for o in options):
                return False
        elif qtype == "noul":
            if not _is_number(a.get("noul")):
                return False
        elif qtype == "score":
            if not _is_number(a.get("score")):
                return False
            probs = a.get("probabilities")
            if probs is not None:
                criteria = q.get("criteria") or []
                if not isinstance(probs, dict) or any(
                    str(i) not in probs for i in range(len(criteria))
                ):
                    return False
        else:
            return False
    return True

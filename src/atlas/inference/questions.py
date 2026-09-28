"""Question-set loading, per-item question/state building, canonical JSON."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

from atlas import paths

SENTENCE_CAP = 255
PARENT_LIMIT = 1500
SENTENCE_MARKER = "SENTENCE_IDS"


@dataclass(frozen=True)
class QuestionSet:
    name: str
    version: int
    label: str  # "<name>@<version>"
    state_fields: list
    questions: dict
    sha256: str  # hex SHA-256 of the raw question file bytes (run manifest)
    parent_limit: int = PARENT_LIMIT


def load_question_set(name: str, version: int) -> QuestionSet:
    path = paths.CONFIGS / "questions" / f"{name}.v{version}.json"
    raw = path.read_bytes()
    data = json.loads(raw)
    return QuestionSet(
        name=data["name"],
        version=data["version"],
        label=f"{data['name']}@{data['version']}",
        state_fields=list(data.get("state_fields") or []),
        questions=data["questions"],
        sha256=hashlib.sha256(raw).hexdigest(),
        parent_limit=int(data.get("parent_limit", PARENT_LIMIT)),
    )


def questions_for(qs: QuestionSet, sentences: list) -> dict:
    """Deep copy of qs.questions with each SENTENCE_IDS criterion expanded to
    {"s0": None, ...} for this item's sentences (at most 255)."""
    questions = copy.deepcopy(qs.questions)
    expanded = {f"s{i}": None for i in range(min(len(sentences or []), SENTENCE_CAP))}
    for q in questions.values():
        if q.get("criteria") == SENTENCE_MARKER:
            q["criteria"] = dict(expanded)
    return questions


def build_state(
    comment: str,
    parent: str | None,
    story_title: str,
    thread_type: str,
    sentences: list | None,
    fields: list,
    parent_limit: int = PARENT_LIMIT,
) -> dict:
    """State dict for the request body, restricted to `fields`."""
    values = {
        "comment": comment,
        "parent": (parent or "")[:parent_limit],
        "story_title": story_title,
        "thread_type": thread_type,
        "sentences": {
            f"s{i}": s for i, s in enumerate((sentences or [])[:SENTENCE_CAP])
        },
    }
    return {f: values[f] for f in fields}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

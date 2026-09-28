"""Append-only human label store.

Primary labels go to ``labels.jsonl``; repeat-view labels (for intra-rater
agreement) go to ``repeats.jsonl`` so they never overwrite primary labels.
Both files use the contract ``LABELS`` schema, one JSON object per line.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from atlas import contracts, paths
from atlas.evaluation.modes import get as _mode

_FIXED_VALUES = {"firsthand_problem": ("yes", "no", "unsure")}


def allowed_values(label_set: str | None = None) -> dict[str, tuple[str, ...]]:
    """Allowed label values per question.

    For a mode label set (see ``atlas.evaluation.modes``) the mode's radio
    questions apply. Otherwise ``firsthand_problem`` is fixed and choice
    questions take the option keys (in file order) of
    ``questions.<id>.criteria`` in ``screen.v0.json``.
    """
    mode = _mode(label_set)
    if mode is not None:
        return dict(mode.QUESTIONS)
    screen = paths.CONFIGS / "questions" / "screen.v0.json"
    criteria = json.loads(screen.read_text(encoding="utf-8"))["questions"]
    out = dict(_FIXED_VALUES)
    for question_id, spec in criteria.items():
        if question_id not in out:
            out[question_id] = tuple(spec["criteria"].keys())
    return out


def labels_path() -> Path:
    return paths.LABELS / "labels.jsonl"


def repeats_path() -> Path:
    return paths.LABELS / "repeats.jsonl"


class LabelStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def add(
        self,
        *,
        comment_id: int,
        label_set: str,
        question_id: str,
        value: str,
        rubric_version: str,
        reviewer: str,
        started_at: str,
        ended_at: str,
        seconds: float,
    ) -> dict:
        mode = _mode(label_set)
        if mode is None:
            allowed = allowed_values()
            if question_id not in allowed:
                raise ValueError(f"unknown question_id: {question_id}")
            if value not in allowed[question_id]:
                raise ValueError(
                    f"value {value!r} not allowed for {question_id}"
                )
        elif question_id in mode.QUESTIONS:
            if value not in mode.QUESTIONS[question_id]:
                raise ValueError(
                    f"value {value!r} not allowed for {question_id}"
                )
        elif question_id in mode.FREE_TEXT:
            limit = mode.FREE_TEXT[question_id]
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(
                    f"free-text value for {question_id} exceeds {limit} chars"
                )
        else:
            raise ValueError(f"unknown question_id: {question_id}")
        values = {
            "label_id": uuid.uuid4().hex,
            "comment_id": int(comment_id),
            "label_set": label_set,
            "question_id": question_id,
            "value": value,
            "rubric_version": rubric_version,
            "reviewer": reviewer,
            "started_at": started_at,
            "ended_at": ended_at,
            "seconds": float(seconds),
        }
        row = {name: values[name] for name in contracts.LABELS.names}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return row

    def all_rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def latest(self, label_set: str) -> dict[tuple[int, str], dict]:
        out: dict[tuple[int, str], dict] = {}
        for row in self.all_rows():
            if row["label_set"] == label_set:
                out[(row["comment_id"], row["question_id"])] = row
        return out

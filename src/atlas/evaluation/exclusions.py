"""Label rows that must not count in any evaluation.

Two exclusion files live under ``paths.LABELS``:

- ``unblinded.json``: ``{"reason", "comment_ids", "recorded_at"}`` —
  comments whose Jev answers were shown to the reviewer before labeling;
  the whole comment is excluded.
- ``void_<label_set>.json``: ``{"reason", "label_set", "label_ids"}`` —
  label rows saved by a UI bug (or otherwise voided). Only those rows are
  dropped, so an earlier valid label survives a later voided one.
"""

from __future__ import annotations

import json

from atlas import paths
from atlas.evaluation.store import LabelStore


def excluded_comment_ids() -> dict[int, str]:
    """comment_id -> reason from unblinded.json; {} when it is missing."""
    path = paths.LABELS / "unblinded.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    reason = str(data.get("reason") or "unblinded")
    return {int(c): reason for c in data.get("comment_ids") or []}


def excluded_label_ids(label_set: str | None = None) -> dict[str, str]:
    """label_id -> reason from every ``void_*.json`` under ``paths.LABELS``.

    With `label_set`, only files pinned to that set (or to no set) apply.
    """
    out: dict[str, str] = {}
    directory = paths.LABELS
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("void_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if label_set is not None and data.get("label_set") not in (
            None,
            label_set,
        ):
            continue
        reason = str(data.get("reason") or path.stem)
        for label_id in data.get("label_ids") or []:
            out[str(label_id)] = reason
    return out


def latest(path, label_set: str) -> tuple[dict, dict]:
    """(last-row-wins labels, exclusion stats) for `label_set`.

    Excluded rows are dropped before last-row-wins, so an earlier valid
    label survives a later voided one. The stats dict is
    ``{"n_excluded": int, "excluded_reasons": {reason: count}}``.
    """
    comments = excluded_comment_ids()
    labels = excluded_label_ids(label_set)
    out: dict = {}
    reasons: dict[str, int] = {}
    n_excluded = 0
    for row in LabelStore(path).all_rows():
        if row["label_set"] != label_set:
            continue
        reason = comments.get(row["comment_id"]) or labels.get(
            row["label_id"]
        )
        if reason is not None:
            n_excluded += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        out[(row["comment_id"], row["question_id"])] = row
    return out, {"n_excluded": n_excluded, "excluded_reasons": reasons}

"""Pre-dispatch cost estimates calibrated from past ledger input_tokens.

Ledger rows store reported input_tokens but not request-body bytes, so bytes
are rebuilt from the items exactly as the runner builds them. `fit_calibration`
least-squares fits input_tokens on body bytes per question set;
`estimate_cost` applies that fit and falls back to the runner's bytes/3.2
heuristic when a question set has no calibration rows.
"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Iterable

import numpy as np

from atlas import paths
from atlas.inference.ledger import read_rows
from atlas.inference.questions import (
    QuestionSet,
    build_state,
    canonical_json,
    load_question_set,
    questions_for,
)


def input_price(model: str) -> float:
    """USD per input token for `model` from configs/prices.toml."""
    prices = tomllib.loads(
        (paths.CONFIGS / "prices.toml").read_text(encoding="utf-8")
    )
    row = next(r for r in prices["price"] if r["model"] == model)
    return row["input_usd_per_million"] / 1e6


def body_bytes(item: dict, qs: QuestionSet, model: str) -> int:
    """UTF-8 length of the canonical request body, built as runner._process."""
    sentences = item.get("sentences") or []
    state = build_state(
        comment=item["comment"],
        parent=item.get("parent"),
        story_title=item.get("story_title"),
        thread_type=item.get("thread_type"),
        sentences=sentences,
        fields=qs.state_fields,
    )
    body = {
        "state": state,
        "model": model,
        "questions": questions_for(qs, sentences),
    }
    return len(canonical_json(body).encode("utf-8"))


def load_label(label: str) -> QuestionSet:
    """"screen@1" -> load_question_set("screen", 1)."""
    name, sep, version = label.rpartition("@")
    if not sep or not name or not version.isdigit():
        raise ValueError(
            f"bad question-set label {label!r}, expected <name>@<version>"
        )
    return load_question_set(name, int(version))


def _fit(xs: list[float], ys: list[float]) -> dict:
    if len(set(xs)) >= 2:
        slope, intercept = np.polyfit(np.asarray(xs), np.asarray(ys), 1)
    else:
        slope, intercept = float(np.mean(ys)) / xs[0], 0.0
    return {"slope": float(slope), "intercept": float(intercept), "n": len(xs)}


def fit_calibration(
    ledger_paths: Iterable,
    items: Iterable[dict],
    model: str = "jev-1.13.0",
) -> dict[str, dict]:
    """Per question_set label, least-squares input_tokens = slope*bytes +
    intercept over calculated ledger rows whose comment_id is in `items`."""
    by_id = {it["comment_id"]: it for it in items}
    sets: dict[str, QuestionSet] = {}
    xs: dict[str, list[float]] = {}
    ys: dict[str, list[float]] = {}
    for lp in ledger_paths:
        for row in read_rows(lp):
            if (
                row.get("cost_class") != "calculated"
                or row.get("input_tokens") is None
                or not row.get("question_set")
            ):
                continue
            item = by_id.get(row.get("comment_id"))
            if item is None:
                continue
            label = row["question_set"]
            if label not in sets:
                try:
                    sets[label] = load_label(label)
                except (ValueError, OSError):
                    continue
            xs.setdefault(label, []).append(body_bytes(item, sets[label], model))
            ys.setdefault(label, []).append(float(row["input_tokens"]))
    return {label: _fit(x, ys[label]) for label, x in xs.items()}


def estimate_cost(
    items: Iterable[dict],
    qs: QuestionSet,
    model: str,
    calibration: dict[str, dict],
    usd_per_input_token: float | None = None,
) -> dict:
    """Upper-bound cost: one call per item (cache and done-set are ignored)."""
    if usd_per_input_token is None:
        usd_per_input_token = input_price(model)
    items = list(items)
    cal = calibration.get(qs.label)
    tokens = 0
    for item in items:
        nbytes = body_bytes(item, qs, model)
        if cal is not None:
            tokens += max(1, math.ceil(cal["slope"] * nbytes + cal["intercept"]))
        else:
            tokens += math.ceil(nbytes / 3.2)
    return {
        "question_set": qs.label,
        "calls": len(items),
        "est_input_tokens": tokens,
        "est_usd": tokens * usd_per_input_token,
        "method": "calibrated" if cal is not None else "bytes/3.2",
    }

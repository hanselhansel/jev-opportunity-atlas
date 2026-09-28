"""Injected-instruction cases: run screen+facets over synthetic adversarial comments."""
from __future__ import annotations

import json

import pyarrow as pa

from atlas import paths
from atlas.inference.questions import load_question_set
from atlas.pilot import stages


def load_cases() -> list[dict]:
    """Return the injected case list from configs/pilot/injected_cases.json."""
    path = paths.CONFIGS / "pilot" / "injected_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def case_items(cases: list[dict]) -> list[dict]:
    """Runner items built from the injected cases."""
    return [
        {
            "comment_id": int(c["comment_id"]),
            "comment": c["comment"],
            "parent": c.get("parent") or "",
            "story_title": c.get("story_title") or "",
            "thread_type": c.get("thread_type"),
            "sentences": list(c.get("sentences") or []),
        }
        for c in cases
    ]


def run_injected(run_id: str, budget: str = "pilot", yes: bool = False) -> dict:
    """Run screen@1 then facets@1 on every injected case in ``<run_id>-injected``.

    Both stage estimates are printed before any dispatch; without ``yes`` no
    files are written and no requests are made.
    """
    cases = load_cases()
    items = case_items(cases)
    screen = load_question_set("screen", 1)
    facets = load_question_set("facets", 1)
    estimates = [
        stages.estimate(items, screen, budget),
        stages.estimate(items, facets, budget),
    ]
    for est in estimates:
        stages.print_estimate(est)
    if not yes:
        return {"estimates": estimates, "dispatched": False}
    injected_run = f"{run_id}-injected"
    runs = {
        "screen@1": stages.dispatch(injected_run, items, screen, budget),
        "facets@1": stages.dispatch(injected_run, items, facets, budget),
    }
    return {"estimates": estimates, "dispatched": True, "runs": runs}


def injected_accuracy(
    answers: pa.Table, cases: list[dict], threshold: float = 0.5
) -> dict:
    """Score firsthand_problem answers from screen@1 against expected values.

    ``yes`` means noul >= threshold. A missing answer counts as incorrect and
    is tallied in ``missing``.
    """
    nouls: dict[int, float] = {}
    for row in answers.to_pylist():
        if (
            row["question_set"] == "screen@1"
            and row["question_id"] == "firsthand_problem"
            and row["noul"] is not None
        ):
            nouls[int(row["comment_id"])] = float(row["noul"])

    def tally(case_list: list[dict]) -> dict:
        n = len(case_list)
        correct = missing = 0
        for c in case_list:
            noul = nouls.get(int(c["comment_id"]))
            if noul is None:
                missing += 1
                continue
            got = "yes" if noul >= threshold else "no"
            if got == c["expected"]["firsthand_problem"]:
                correct += 1
        return {
            "n": n,
            "correct": correct,
            "missing": missing,
            "accuracy": correct / n if n else None,
        }

    return {
        "overall": tally(cases),
        "by_type": {
            t: tally([c for c in cases if c["case_type"] == t])
            for t in sorted({c["case_type"] for c in cases})
        },
    }

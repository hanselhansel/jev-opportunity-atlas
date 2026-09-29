"""Scoring for the synthetic benchmark: every pipeline stage measured
against the known answers of the invented cases. Output is always labeled
as synthetic — never real-data accuracy."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.benchmark.run import FACETS, card_cases, load_cases
from atlas.cards.engine import assign
from atlas.cards.engine.cardset import load_cardset
from atlas.pilot import packed

THRESHOLDS = (0.5, 0.7)
DISCLAIMER = "Synthetic benchmark (invented cases; not real-data accuracy)"


def _meta(run_dir: Path) -> dict:
    path = run_dir / "benchmark.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _nouls(answers: dict, qid: str) -> dict[int, float]:
    return {
        int(cid): by_q[qid]["noul"]
        for cid, by_q in answers.items()
        if by_q.get(qid) is not None
    }


def _packed_nouls(run_dir: Path) -> dict[int, float]:
    """firsthand_problem noul per comment, unpacked through packed_map."""
    path = run_dir / "packed_map.parquet"
    if not path.exists():
        return {}
    rows = assign.read_answers(run_dir, packed.PACKED_LABEL)
    flat = [
        {"comment_id": pid, "question_id": qid, "noul": r["noul"]}
        for pid, by_q in rows.items()
        for qid, r in by_q.items()
    ]
    table = pa.Table.from_pylist(flat, schema=packed.UNPACKED)
    unpacked = packed.unpack_answers(table, pq.read_table(path))
    return {
        int(r["comment_id"]): r["noul"]
        for r in unpacked.to_pylist()
        if r["question_id"] == "firsthand_problem"
    }


def _binary(cases: list[dict], nouls: dict, t: float) -> dict:
    """Predicted yes iff noul >= t; a missing noul predicts "no"."""
    tp = fp = fn = tn = missing = 0
    for c in cases:
        noul = nouls.get(int(c["id"]))
        pred = noul is not None and noul >= t
        missing += noul is None
        if (c.get("expected") or {}).get("firsthand_problem") == "yes":
            tp += pred
            fn += not pred
        else:
            fp += pred
            tn += not pred
    n = len(cases)
    return {
        "n": n,
        "n_missing": missing,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": (tp + tn) / n if n else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def _by_category(cases: list[dict], nouls: dict) -> dict:
    out: dict[str, dict] = {}
    for c in cases:
        noul = nouls.get(int(c["id"]))
        pred = noul is not None and noul >= 0.5
        want = (c.get("expected") or {}).get("firsthand_problem") == "yes"
        e = out.setdefault(c["category"], {"n": 0, "correct": 0})
        e["n"] += 1
        e["correct"] += int(pred == want)
    return {
        cat: {**e, "accuracy": e["correct"] / e["n"]}
        for cat, e in sorted(out.items())
    }


def _choice_p(row: dict) -> float | None:
    """Probability of the chosen option, else the row's confidence."""
    raw = row.get("probabilities_json")
    if raw:
        return json.loads(raw).get(row.get("choice"))
    return row.get("confidence")


def _account_type(cases: list[dict], answers: dict) -> dict:
    n = correct = missing = 0
    for c in cases:
        row = (answers.get(int(c["id"])) or {}).get("account_type")
        got = row.get("choice") if row else None
        missing += got is None
        correct += int(
            got is not None
            and got == (c.get("expected") or {}).get("account_type")
        )
        n += 1
    return {
        "n": n,
        "correct": correct,
        "missing": missing,
        "accuracy": correct / n if n else None,
    }


def _facet_got(row, facet: str):
    if row is None:
        return None
    if facet == "resolution":
        return row.get("choice")
    noul = row.get("noul")
    return None if noul is None else ("yes" if noul >= 0.5 else "no")


def _facet_p(row, facet: str):
    if row is None:
        return None
    if facet == "resolution":
        return row.get("confidence")
    return row.get("noul")


def _facets(cases: list[dict], answers: dict) -> dict:
    out: dict[str, dict] = {}
    for facet in FACETS:
        n = correct = missing = 0
        for c in cases:
            expected = c.get("expected") or {}
            if facet not in expected:
                continue
            n += 1
            got = _facet_got(
                (answers.get(int(c["id"])) or {}).get(facet), facet
            )
            if got is None:
                missing += 1
            else:
                correct += int(got == expected[facet])
        out[facet] = {
            "n": n,
            "correct": correct,
            "missing": missing,
            "accuracy": correct / n if n else None,
        }
    return out


def _card_got(row):
    if row is None:
        return None
    if row["group_id"] == "none" or row["card_id"] == "none":
        return "none"
    return row["card_id"]


def _assignment_rows(run_dir: Path, version: str) -> dict[int, dict]:
    path = assign.assignments_path(run_dir, version)
    if not path.exists():
        return {}
    return {r["comment_id"]: r for r in assign.load_assignments(run_dir, version).rows}


def _cards(cases: list[dict], rows: dict, cs) -> dict:
    out = {
        "n": 0,
        "correct": 0,
        "top1_accuracy": None,
        "none": {"n": 0, "correct": 0},
        "carded": {"n": 0, "correct": 0, "false_none": 0, "group_correct": 0},
    }
    for c in card_cases(cases):
        expected = (c.get("expected") or {}).get("card")
        row = rows.get(int(c["id"]))
        got = _card_got(row)
        out["n"] += 1
        out["correct"] += int(got == expected)
        if expected == "none":
            out["none"]["n"] += 1
            out["none"]["correct"] += int(got == "none")
        else:
            carded = out["carded"]
            carded["n"] += 1
            carded["correct"] += int(got == expected)
            carded["false_none"] += int(got == "none")
            want_group = (
                cs.all_cards[expected].group_id
                if expected in cs.all_cards
                else None
            )
            carded["group_correct"] += int(
                row is not None and row["group_id"] == want_group
            )
    if out["n"]:
        out["top1_accuracy"] = out["correct"] / out["n"]
    return out


def _misses(
    cases, single, packed_nouls, answers_single, answers_facets, card_rows
) -> list[dict]:
    out: list[dict] = []
    for c in cases:
        cid = int(c["id"])
        expected = c.get("expected") or {}
        want_yes = expected.get("firsthand_problem") == "yes"
        for mode, nouls in (("single", single), ("packed", packed_nouls)):
            noul = nouls.get(cid)
            pred = None if noul is None else ("yes" if noul >= 0.5 else "no")
            # A missing noul predicts "no"; the miss entry keeps got=None.
            if (pred == "yes") != want_yes:
                out.append(
                    {
                        "case_id": cid,
                        "category": c["category"],
                        "question": f"firsthand_problem/{mode}",
                        "expected": expected.get("firsthand_problem"),
                        "got": pred,
                        "p": noul,
                    }
                )
        row = (answers_single.get(cid) or {}).get("account_type")
        got = row.get("choice") if row else None
        if got != expected.get("account_type"):
            out.append(
                {
                    "case_id": cid,
                    "category": c["category"],
                    "question": "account_type",
                    "expected": expected.get("account_type"),
                    "got": got,
                    "p": _choice_p(row) if row else None,
                }
            )
        for facet in FACETS:
            if facet not in expected:
                continue
            row = (answers_facets.get(cid) or {}).get(facet)
            got = _facet_got(row, facet)
            if got != expected[facet]:
                out.append(
                    {
                        "case_id": cid,
                        "category": c["category"],
                        "question": facet,
                        "expected": expected[facet],
                        "got": got,
                        "p": _facet_p(row, facet),
                    }
                )
        if "card" in expected:
            row = card_rows.get(cid)
            got = _card_got(row)
            if got != expected["card"]:
                out.append(
                    {
                        "case_id": cid,
                        "category": c["category"],
                        "question": "card",
                        "expected": expected["card"],
                        "got": got,
                        "p": row.get("card_p") if row else None,
                    }
                )
    out.sort(key=lambda m: (m["question"], m["case_id"]))
    return out


def score_benchmark(run_id) -> dict:
    run_dir = paths.run_dir(run_id)
    meta = _meta(run_dir)
    version = meta.get("cases_version", "v1")
    cases = load_cases(version)
    answers_single = assign.read_answers(run_dir, "screen@1")
    answers_facets = assign.read_answers(run_dir, "facets@2")
    nouls = {
        "single": _nouls(answers_single, "firsthand_problem"),
        "packed": _packed_nouls(run_dir),
    }
    cardset = meta.get("cardset", "pilot.t1")
    cs_name, cs_version = cardset.split(".", 1)
    cs = load_cardset(cs_name, cs_version)
    card_rows = _assignment_rows(run_dir, cs_version)
    return {
        "run_id": run_id,
        "cases_version": version,
        "n_cases": len(cases),
        "disclaimer": DISCLAIMER,
        "firsthand": {
            mode: {str(t): _binary(cases, n, t) for t in THRESHOLDS}
            for mode, n in nouls.items()
        },
        "by_category": {
            mode: _by_category(cases, n) for mode, n in nouls.items()
        },
        "account_type": _account_type(cases, answers_single),
        "facets": _facets(cases, answers_facets),
        "cards": _cards(cases, card_rows, cs),
        "misses": _misses(
            cases,
            nouls["single"],
            nouls["packed"],
            answers_single,
            answers_facets,
            card_rows,
        ),
    }


def write_report(run_id) -> Path:
    """Score the run and write benchmark_score.json + benchmark_report.md."""
    from atlas.benchmark.report import render_markdown

    s = score_benchmark(run_id)
    run_dir = paths.run_dir(run_id)
    (run_dir / "benchmark_score.json").write_text(
        json.dumps(s, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    path = run_dir / "benchmark_report.md"
    path.write_text(render_markdown(s), encoding="utf-8")
    return path

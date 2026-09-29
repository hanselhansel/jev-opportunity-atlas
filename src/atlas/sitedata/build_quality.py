"""``runs`` rows from attempt ledgers and ``quality`` rows from evaluations.

Runs: calls, attempts, retries, unknown attempts, calculated USD, p50/p95
request latency, cache replays, and wall time (first start to last end).
Quality: the assignment and facet audits (Jev and the random-card control),
screen evaluations for the chosen label sets (Jev and the keyword baseline),
and the synthetic benchmark, whose rows carry ``label_set = "synthetic"``.
"""

from __future__ import annotations

import json
import tomllib
from datetime import datetime
from pathlib import Path

from atlas import paths
from atlas.inference import ledger

AUDIT_SETS = ("assignment_audit", "facet_audit")


def _ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def _run_row(run_id: str, phase: str) -> dict | None:
    path = paths.ledger_path(run_id)
    if not path.exists():
        return None
    rows = ledger.read_rows(path)
    s = ledger.summarize(path)
    network = [
        r for r in rows if r.get("cost_class") not in ("pending", "replay")
    ] + ledger.unresolved_pending(rows)
    starts = [t for t in (_ts(r.get("started_at")) for r in rows) if t is not None]
    ends = [t for t in (_ts(r.get("ended_at")) for r in rows) if t is not None]
    return {
        "run_id": run_id,
        "phase": phase,
        "calls": s["logical_calls"],
        "attempts": s["attempts"],
        "retries": s["attempts"] - len({r.get("logical_call_id") for r in network}),
        "unknown_attempts": s["unknown_attempts"],
        "calculated_usd": s["calculated_usd"],
        "wall_s": (max(ends) - min(starts)) if starts and ends else None,
        "p50_ms": s["p50_request_ms"],
        "p95_ms": s["p95_request_ms"],
        "cache_hits": s["replays"],
        "kind": "jev",
    }


def runs_rows(roles: list[tuple[str, str]]) -> list[dict]:
    """One row per distinct run id; a run used in two roles gets both phases."""
    phases: dict[str, list[str]] = {}
    for phase, run_id in roles:
        if run_id:
            phases.setdefault(run_id, [])
            if phase not in phases[run_id]:
                phases[run_id].append(phase)
    out = []
    for run_id, ph in phases.items():
        row = _run_row(run_id, "+".join(ph))
        if row is not None:
            out.append(row)
    return out


def runs_from_phases(toml_path) -> list[dict]:
    """One row per key in the TOML ``[runs]`` map of run_id -> phase.

    A key ``a/b`` reads ``runs/a/b/ledger.jsonl`` and is written as ``a/b``.
    A key whose ledger is missing is an error naming the key.
    """
    from atlas.sitedata.build import SiteDataError

    with Path(toml_path).open("rb") as f:
        phases = tomllib.load(f).get("runs", {})
    rows, missing = [], []
    for run_id, phase in phases.items():
        row = _run_row(str(run_id), str(phase))
        if row is None:
            missing.append(str(run_id))
        else:
            rows.append(row)
    if missing:
        raise SiteDataError(
            f"run_phases ledger missing for: {', '.join(missing)}"
        )
    return rows


def _row(question_id, label_set, metric, value, ci, n, system="jev") -> dict:
    lo, hi = (ci or [None, None])[:2]
    return {
        "question_id": question_id,
        "label_set": label_set,
        "metric": metric,
        "value": value,
        "ci_low": lo,
        "ci_high": hi,
        "n": n,
        "system": system,
    }


def _assignment_audit(r: dict) -> list[dict]:
    out = []
    for key, system in (("jev", "jev"), ("random", "random_card")):
        g = (r.get("groups") or {}).get(key)
        if not g:
            continue
        n = g.get("n", 0) - g.get("n_unsure", 0)
        for mode in ("strict", "lenient"):
            m = g.get(mode) or {}
            out.append(
                _row(
                    "card_assignment",
                    r["label_set"],
                    f"precision_{mode}",
                    m.get("precision"),
                    m.get("ci"),
                    n,
                    system,
                )
            )
    return out


def _facet_audit(r: dict) -> list[dict]:
    out = []
    for qid, m in (r.get("facets") or {}).items():
        for metric in ("precision", "recall"):
            out.append(
                _row(
                    qid,
                    r["label_set"],
                    metric,
                    m.get(metric),
                    m.get(f"{metric}_ci"),
                    m.get("n"),
                )
            )
    return out


def _screen_eval(r: dict) -> list[dict]:
    out = []
    q = r.get("question", "firsthand_problem")
    for system, m in (("jev", r.get("metrics")), (None, r.get("baseline"))):
        if not m or "precision" not in m:
            continue
        name = system or m.get("name", "baseline")
        for metric in ("precision", "recall", "f1"):
            if metric in m:
                out.append(
                    _row(
                        q,
                        r["label_set"],
                        metric,
                        m[metric],
                        m.get(f"{metric}_ci"),
                        m.get("n"),
                        name,
                    )
                )
    return out


def _benchmark(run_id: str) -> list[dict]:
    path = paths.run_dir(run_id) / "benchmark_score.json"
    if not path.exists():
        return []
    s = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for mode, qid in (
        ("single", "firsthand_problem"),
        ("packed", "firsthand_problem_packed"),
    ):
        m = ((s.get("firsthand") or {}).get(mode) or {}).get("0.5")
        if m:
            out.append(
                _row(qid, "synthetic", "accuracy", m.get("accuracy"), None, m.get("n"))
            )
    at = s.get("account_type")
    if at:
        out.append(
            _row(
                "account_type",
                "synthetic",
                "accuracy",
                at.get("accuracy"),
                None,
                at.get("n"),
            )
        )
    for facet, m in (s.get("facets") or {}).items():
        out.append(
            _row(facet, "synthetic", "accuracy", m.get("accuracy"), None, m.get("n"))
        )
    cards = s.get("cards")
    if cards:
        out.append(
            _row(
                "card_assignment",
                "synthetic",
                "top1_accuracy",
                cards.get("top1_accuracy"),
                None,
                cards.get("n"),
            )
        )
    return out


def _eval_rows(report: dict, ls: str) -> list[dict]:
    report.setdefault("label_set", ls)
    if ls == "assignment_audit":
        return _assignment_audit(report)
    if ls == "facet_audit":
        return _facet_audit(report)
    return _screen_eval(report)


def quality_rows(run_ids, label_sets, benchmark_run=None, audit_runs=()) -> list[dict]:
    """Rows from each run's ``eval_*.json`` reports.

    ``audit_runs`` are runs named explicitly for their audit reports: every
    ``eval_*.json`` they hold is included (no label-set filter), and their
    reports win over a role run's report of the same name.
    """
    out = []
    seen = set()
    ordered = [(r, True) for r in audit_runs or ()] + [
        (r, False) for r in run_ids
    ]
    for run_id, audit in ordered:
        if not run_id or (not audit and run_id == benchmark_run):
            continue
        for path in sorted(paths.run_dir(run_id).glob("eval_*.json")):
            ls = path.stem[len("eval_") :]
            if ls in seen or (
                not audit and ls not in AUDIT_SETS and ls not in label_sets
            ):
                continue
            seen.add(ls)
            report = json.loads(path.read_text(encoding="utf-8"))
            out += _eval_rows(report, ls)
    if benchmark_run:
        out += _benchmark(benchmark_run)
    return out

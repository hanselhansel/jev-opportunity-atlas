"""The ``method`` section: run table, cost totals, and quality evidence.

Runs come from ``configs/run_phases.toml`` through
``sitedata.build_quality.runs_from_phases`` so the story reports exactly the
same ledger-derived spend as the site. Quality evidence is read back from
the saved artifacts: the assignment audit (Jev vs the random-card control),
the synthetic benchmark accuracy, planted-need recovery from the planted
run's saved result JSON (falling back to a recompute from its saved
assignments), and the robustness comparison JSONs for screen prevalence and
assignment agreement.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from atlas import paths
from atlas.story.io import est as _est


def run_phases(toml_path) -> dict:
    """The ``[runs]`` map of run id -> phase from a run_phases TOML file."""
    p = Path(toml_path)
    if not p.is_absolute():
        p = paths.ROOT / p
    if not p.exists():
        return {}
    with p.open("rb") as f:
        return tomllib.load(f).get("runs", {})


def _audit_precisions(audit_run):
    path = paths.run_dir(audit_run) / "eval_assignment_audit.json"
    if not path.exists():
        return None, None
    groups = (json.loads(path.read_text(encoding="utf-8")).get("groups")) or {}
    jev = (groups.get("jev") or {}).get("strict") or {}
    rnd = (groups.get("random") or {}).get("strict") or {}
    return jev.get("precision"), rnd.get("precision")


def _benchmark_acc(benchmark_run):
    path = paths.run_dir(benchmark_run) / "benchmark_score.json"
    if not path.exists():
        return None
    s = json.loads(path.read_text(encoding="utf-8"))
    single = (s.get("firsthand") or {}).get("single") or {}
    return (single.get("0.5") or {}).get("accuracy")


def _planted_recovery(phases: dict):
    """Recovery share: the run's saved ``planted-<version>.json`` first,
    else recomputed from its saved assignments."""
    from atlas.cards.engine.assign import load_assignments
    from atlas.cards.engine.planted import load_planted, planted_score

    cands = sorted(
        (r for r in phases if "planted" in r),
        key=lambda r: (not r.startswith("main-"), r),
    )
    for rid in cands:
        run_dir = paths.run_dir(rid)
        for p in sorted(run_dir.glob("planted-*.json")):
            ver = p.name[len("planted-") : -len(".json")]
            if "+planted-" not in ver:
                continue
            try:
                score = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(score, dict) and score.get("recovery") is not None:
                return score["recovery"]
        for p in sorted(run_dir.glob("assignments-*.parquet")):
            ver = p.name[len("assignments-") : -len(".parquet")]
            if "+planted-" not in ver:
                continue
            try:
                score = planted_score(
                    load_assignments(run_dir, ver).rows,
                    load_planted(ver.split("+planted-")[-1]),
                )
            except (OSError, KeyError, ValueError):
                continue
            return score.get("recovery")
    return None


def _read_json(rel):
    p = Path(rel)
    if not p.is_absolute():
        p = paths.ROOT / p
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _wording_screen(robust_screen_json) -> list[dict]:
    runs = (_read_json(robust_screen_json).get("runs")) or {}
    return [
        {
            "run": rid,
            "prevalence": _est(
                r.get("prevalence"),
                lo95=r.get("ci_low"),
                hi95=r.get("ci_high"),
                n=r.get("n") or 0,
            ),
        }
        for rid, r in sorted(runs.items())
    ]


def _wording_assign(robust_assign_json) -> dict:
    runs = (_read_json(robust_assign_json).get("runs")) or {}
    return {
        key: [r.get(key) for _, r in sorted(runs.items())]
        for key in ("card_agreement", "group_agreement")
    }


def build_method(
    run_phases_toml,
    audit_run,
    benchmark_run,
    robust_screen_json,
    robust_assign_json,
) -> dict:
    from atlas.sitedata.build_quality import runs_from_phases

    toml_path = Path(run_phases_toml)
    if not toml_path.is_absolute():
        toml_path = paths.ROOT / toml_path
    rows = runs_from_phases(toml_path)
    runs = [
        {
            "run": r["run_id"],
            "phase": r["phase"],
            "calls": r["calls"],
            "usd": r["calculated_usd"],
            "p50_ms": r["p50_ms"],
            "wall_s": r["wall_s"],
        }
        for r in rows
    ]
    audit_jev, audit_random = _audit_precisions(audit_run)
    return {
        "runs": runs,
        "total_usd": round(sum(r["usd"] or 0.0 for r in runs), 6),
        "total_calls": sum(r["calls"] or 0 for r in runs),
        "quality": {
            "audit_jev": audit_jev,
            "audit_random": audit_random,
            "benchmark_acc": _benchmark_acc(benchmark_run),
            "planted_recovery": _planted_recovery(run_phases(run_phases_toml)),
        },
        "wording": {
            "screen": _wording_screen(robust_screen_json),
            "assign": _wording_assign(robust_assign_json),
        },
    }

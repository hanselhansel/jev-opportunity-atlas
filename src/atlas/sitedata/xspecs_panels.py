"""The wording-robustness, cost, and quality panels of the X chart specs.

Each builder returns its spec dict plus the intermediate rows or totals
``site_chart_specs`` needs to fill ``{placeholder}`` titles.
"""

from __future__ import annotations


def _wording_spec(
    common: dict, robustness: list[dict], run_labels: dict
) -> tuple[dict, list[dict]]:
    prev = [
        r
        for r in robustness
        if r["check"] == "screen_wording" and r["metric"] == "prevalence"
    ]
    para_runs = {
        r["run_id"]
        for r in robustness
        if r["metric"] in ("agreement", "kappa", "spearman")
    }
    spec = {
        **common,
        "kind": "bars",
        "name": "wording_range",
        "run_id": "+".join(r["run_id"] for r in prev) or "none",
        "denominator": (
            f"{prev[0]['n']:,} comments in the paraphrase subsample"
            if prev and prev[0].get("n")
            else "comments in the paraphrase subsample"
        ),
        "n": prev[0]["n"] if prev else 0,
        "title": "The headline prevalence moves this much when the question is reworded.",
        "data": {
            "rows": [
                {
                    "label": (
                        f"{run_labels.get(r['run_id'], r['run_id'])} (paraphrase)"
                        if r["run_id"] in para_runs
                        else f"{run_labels.get(r['run_id'], r['run_id'])} (main)"
                    ),
                    "value": r["value"],
                    "ci_low": r["lo"],
                    "ci_high": r["hi"],
                }
                for r in prev
            ],
            "xlabel": "prevalence of firsthand problems at the screen cutoff",
            "format": "pct",
        },
    }
    return spec, prev


def _cost_spec(common: dict, runs: list[dict]) -> tuple[dict, float, int]:
    calls = sum(r["calls"] or 0 for r in runs)
    usd = sum(r["calculated_usd"] or 0.0 for r in runs)
    biggest = max(runs, key=lambda r: r["calls"] or 0, default={})
    by_phase: dict[str, dict] = {}
    for r in runs:
        phase = r["phase"] or "unknown"
        b = by_phase.setdefault(
            phase,
            {
                "phase": phase,
                "calculated_usd": 0.0,
                "calls": 0,
                "runs": 0,
                "wall_s": 0.0,
            },
        )
        b["calculated_usd"] += r["calculated_usd"] or 0.0
        b["calls"] += r["calls"] or 0
        b["runs"] += 1
        b["wall_s"] += r["wall_s"] or 0.0
    phases = sorted(
        by_phase.values(), key=lambda b: (-b["calculated_usd"], b["phase"])
    )
    spec = {
        **common,
        "kind": "cost",
        "name": "cost",
        "run_id": (
            f"{len(runs)} runs across {len(phases)} phases" if runs else "none"
        ),
        "denominator": "Jev calls across all runs",
        "n": calls,
        "title": f"The runs behind this atlas cost ${usd:,.2f} of Jev credit over {calls:,} calls.",
        "data": {
            "calculated_usd": usd,
            "calls": calls,
            "p50_ms": biggest.get("p50_ms"),
            "wall_s": sum(r["wall_s"] or 0.0 for r in runs),
            "phases": phases,
        },
    }
    return spec, usd, calls


def _quality_spec(
    common: dict, quality: list[dict], assign_run
) -> tuple[dict, list[dict]]:
    names = {
        "jev": "Jev card assignment (human audit)",
        "random_card": "Random card (baseline)",
    }
    audit = [
        r
        for r in quality
        if r["label_set"] == "assignment_audit"
        and r["metric"] == "precision_strict"
        and r["system"] in names
    ]
    audit.sort(key=lambda r: list(names).index(r["system"]))
    bench = [r for r in quality if r["label_set"] == "synthetic"]
    qrows = [
        {
            "label": names[r["system"]],
            "value": r["value"],
            "ci_low": r["ci_low"],
            "ci_high": r["ci_high"],
        }
        for r in audit
    ]
    qrows += [
        {
            "label": (
                f"{r['question_id'].replace('_', ' ')} "
                f"{r['metric'].replace('_', ' ')} (synthetic cases)"
            ),
            "value": r["value"],
            "synthetic": True,
        }
        for r in bench
    ]
    jev_n = next((r["n"] for r in audit if r["system"] == "jev"), None)
    spec = {
        **common,
        "kind": "quality",
        "name": "quality",
        "run_id": assign_run,
        "denominator": "audited card assignments" if jev_n else "benchmark cases",
        "n": jev_n or sum(r["n"] or 0 for r in bench),
        "title": "The human audit compares Jev's card precision with a random-card baseline.",
        "data": {"rows": qrows, "xlabel": "precision or accuracy"},
    }
    return spec, audit

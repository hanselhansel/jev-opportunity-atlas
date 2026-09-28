"""Synthetic site tables: fictional on purpose, so no screenshot can be mistaken
for a real finding. All ids are >= 9_000_000_000 (outside the real HN id range).
Deterministic: same seed, same bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

DOMAINS = [f"Domain {c}" for c in "ABCDEFGH"]
PERIODS = [f"P{i:02d}" for i in range(1, 13)]
N_EVIDENCE = 400
BUILT_AT = "2026-01-01T00:00:00Z"
RUN_ID = "fixture-run"
QUESTION_SET = "fixture@0"
TAXONOMY = "tax@0"


def _meta() -> dict[str, list]:
    rows = {
        "mode": "fixture",
        "snapshot_id": "fixture-snapshot",
        "run_id": RUN_ID,
        "window_start": "2025-01-01T00:00:00Z",
        "window_end": "2026-01-01T00:00:00Z",
        "built_at": BUILT_AT,
        "question_set": QUESTION_SET,
        "taxonomy_version": TAXONOMY,
        "n_eligible": "48000",
        "n_screened": "1200",
        "source": "synthetic fixture",
    }
    return {"key": list(rows), "value": list(rows.values())}


def _coverage() -> dict[str, list]:
    rows = [("state", "ok", 48000), ("state", "dead", 900)]
    rows += [("period", p, 4000) for p in PERIODS]
    rows += [("thread_type", t, 6000) for t in ("ask_hn", "show_hn", "story")]
    return {
        "dimension": [r[0] for r in rows],
        "key": [r[1] for r in rows],
        "count": [r[2] for r in rows],
    }


def _domain_share(rng: np.random.Generator) -> dict[str, list]:
    cols: dict[str, list] = {k: [] for k in (
        "lane", "domain", "period", "n", "weighted_share", "ci_low", "ci_high",
        "too_few", "badge", "run_id", "question_set", "denominator",
    )}

    def emit(lane, domain, period, n, share, low, high, too_few, badge, denom):
        cols["lane"].append(lane)
        cols["domain"].append(domain)
        cols["period"].append(period)
        cols["n"].append(int(n))
        cols["weighted_share"].append(share)
        cols["ci_low"].append(low)
        cols["ci_high"].append(high)
        cols["too_few"].append(too_few)
        cols["badge"].append(badge)
        cols["run_id"].append(RUN_ID)
        cols["question_set"].append(QUESTION_SET)
        cols["denominator"].append(denom)

    for lane in ("breadth", "discovery"):
        counts = {
            d: [
                int(rng.integers(2, 25)) if d == "Domain H" else int(
                    rng.integers(30, 200)
                )
                for _ in PERIODS
            ]
            for d in DOMAINS
        }
        totals = {
            p: sum(counts[d][i] for d in DOMAINS)
            for i, p in enumerate(PERIODS)
        }
        totals["all"] = sum(totals.values())
        for domain in DOMAINS:
            for i, period in enumerate(PERIODS + ["all"]):
                n = counts[domain][i] if period != "all" else sum(counts[domain])
                if lane == "discovery":
                    emit(
                        lane, domain, period, n, None, None, None, False,
                        "measured", "of the ranked discovery evidence set",
                    )
                else:
                    share = n / totals[period]
                    too_few = domain == "Domain H"
                    if too_few:
                        low = high = None
                    else:
                        spread = float(rng.uniform(0.005, 0.02))
                        low, high = (
                            max(0.0, share - spread),
                            min(1.0, share + spread),
                        )
                    denom = (
                        f"all {totals[period]:,} breadth comments"
                        + ("" if period == "all" else f" in {period}")
                        + f" across {len(DOMAINS)} domains"
                    )
                    emit(
                        lane, domain, period, n, share, low, high, too_few,
                        "estimated", denom,
                    )
    return cols


def _evidence(rng: np.random.Generator) -> dict[str, list]:
    n = N_EVIDENCE
    comment_ids = 9_000_000_000 + rng.choice(500_000_000, size=n, replace=False)
    story_ids = 9_500_000_000 + rng.integers(0, 80, size=n)
    specificity = rng.integers(0, 4, size=n).astype(float)
    concrete = rng.uniform(0, 1, size=n)
    behavior = rng.uniform(0, 1, size=n)
    timing = rng.uniform(0, 1, size=n)
    workaround = rng.uniform(0, 1, size=n)
    consequence = rng.uniform(0, 1, size=n)
    strength = np.mean(
        np.vstack([specificity / 3, concrete, workaround, consequence, behavior, timing]),
        axis=0,
    )
    threads = ["ask_hn", "show_hn", "launch_hn", "story"]
    accounts = ["regular", "new", "throwaway"]
    prob_json = [
        json.dumps(
            {"concrete_task": float(c), "behavior_any": float(b), "timing_current": float(t)},
            sort_keys=True,
        )
        for c, b, t in zip(concrete, behavior, timing)
    ]
    return {
        "comment_id": [int(c) for c in comment_ids],
        "lane": ["breadth" if i % 2 == 0 else "discovery" for i in range(n)],
        "domain": [DOMAINS[i % len(DOMAINS)] for i in range(n)],
        "subtopic": [f"Subtopic {DOMAINS[i % 8][-1]}{(i % 3) + 1}" for i in range(n)],
        "period": [PERIODS[i % len(PERIODS)] for i in range(n)],
        "story_id": [int(s) for s in story_ids],
        "thread_type": [threads[i % len(threads)] for i in range(n)],
        "firsthand_p": [float(x) for x in rng.uniform(0, 1, n)],
        "account_type": [accounts[i % len(accounts)] for i in range(n)],
        "specificity": [float(x) for x in specificity],
        "workaround_p": [float(x) for x in workaround],
        "consequence_any_p": [float(x) for x in consequence],
        "evidence_strength": [float(x) for x in strength],
        "support_sentence_id": [f"s{i % 4}" for i in range(n)],
        "model_returned": ["fixture-model-0"] * n,
        "run_id": [RUN_ID] * n,
        "human_label": [
            "yes" if i % 10 == 0 else ("no" if i % 10 == 5 else None) for i in range(n)
        ],
        "text_sha256": [
            hashlib.sha256(f"synthetic comment {int(c)}".encode()).hexdigest()
            for c in comment_ids
        ],
        "question_set": [QUESTION_SET] * n,
        "taxonomy_version": [TAXONOMY] * n,
        "weight": [float(x) for x in rng.uniform(0.5, 2.0, n)],
        "confidence": [float(x) for x in rng.uniform(0, 1, n)],
        "probabilities_json": prob_json,
    }


_FINDINGS = [
    ("f1", "validated", "Domain A", "Subtopic A1", "breadth", 6, 2, "2026-01-02T00:00:00Z"),
    ("f2", "candidate", "Domain C", "Subtopic C2", "breadth", 4, 1, None),
    ("f3", "candidate", "Domain B", "Subtopic B1", "discovery", 5, 0, None),
]


def _findings() -> dict[str, list]:
    cols: dict[str, list] = {k: [] for k in (
        "finding_id", "title", "domain", "subtopic", "n_comments", "n_threads",
        "n_authors", "months_present", "contradicting", "status", "lane",
        "problem_statement", "user_workflow", "workarounds_json",
        "solutions_named_json", "contradicting_n", "unknowns_json",
        "discovery_question", "first_period", "last_period", "max_thread_share",
        "run_id", "question_set", "taxonomy_version", "validated_at",
    )}
    for fid, status, domain, sub, lane, n_c, n_contra, validated in _FINDINGS:
        cols["finding_id"].append(fid)
        cols["title"].append(f"Synthetic finding {fid} in {domain}")
        cols["domain"].append(domain)
        cols["subtopic"].append(sub)
        cols["n_comments"].append(n_c)
        cols["n_threads"].append(n_c - 1)
        cols["n_authors"].append(n_c - 1)
        cols["months_present"].append(9)
        cols["contradicting"].append(n_contra > 0)
        cols["status"].append(status)
        cols["lane"].append(lane)
        cols["problem_statement"].append(
            f"Synthetic recurring problem statement for {domain}."
        )
        cols["user_workflow"].append(f"Synthetic workflow description for {domain}.")
        cols["workarounds_json"].append(json.dumps(["workaround one", "workaround two"]))
        cols["solutions_named_json"].append(json.dumps(["tool one"]))
        cols["contradicting_n"].append(n_contra)
        cols["unknowns_json"].append(json.dumps(["whether demand survives pricing"]))
        cols["discovery_question"].append(f"What repeats in {domain}?")
        cols["first_period"].append("P01")
        cols["last_period"].append("P11")
        cols["max_thread_share"].append(0.34)
        cols["run_id"].append(RUN_ID)
        cols["question_set"].append(QUESTION_SET)
        cols["taxonomy_version"].append(TAXONOMY)
        cols["validated_at"].append(validated)
    return cols


def _finding_evidence(rng: np.random.Generator, evidence: dict[str, list]) -> dict[str, list]:
    cols: dict[str, list] = {k: [] for k in (
        "finding_id", "comment_id", "match_p", "role"
    )}
    for fid, _status, domain, _sub, _lane, n_c, n_contra, _v in _FINDINGS:
        pool = [
            c for c, d in zip(evidence["comment_id"], evidence["domain"]) if d == domain
        ]
        chosen = pool[:n_c]
        for i, cid in enumerate(chosen):
            cols["finding_id"].append(fid)
            cols["comment_id"].append(cid)
            cols["match_p"].append(float(rng.uniform(0.5, 1.0)))
            cols["role"].append("contradicting" if i < n_contra else "supporting")
    return cols


def _runs() -> dict[str, list]:
    rows = [
        (RUN_ID, "screen", 1200, 1260, 60, 3, 8.41, 540.0, 320.0, 1400.0, 400, "jev"),
        (RUN_ID, "label", 400, 415, 15, 1, 11.02, 210.0, 450.0, 1900.0, 90, "jev"),
        ("fixture-run-2", "label", 40, 42, 2, 0, 1.10, 30.0, 460.0, 1800.0, 8, "jev"),
        ("fixture-run-2", "replay", 40, 40, 0, 0, 0.0, 4.0, 5.0, 12.0, 40, "replay"),
    ]
    keys = (
        "run_id", "phase", "calls", "attempts", "retries", "unknown_attempts",
        "calculated_usd", "wall_s", "p50_ms", "p95_ms", "cache_hits", "kind",
    )
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


def _quality() -> dict[str, list]:
    rows = [
        ("q_firsthand", "calibration", "accuracy", 0.86, 0.78, 0.92, 120),
        ("q_workaround", "calibration", "accuracy", 0.81, 0.72, 0.88, 120),
        ("q_consequence", "calibration", "accuracy", 0.77, 0.68, 0.85, 120),
        ("q_firsthand", "heldout", "accuracy", 0.83, 0.70, 0.92, 60),
        ("q_workaround", "heldout", "f1", 0.74, 0.60, 0.85, 60),
        ("q_specificity", "calibration", "mae", 0.41, 0.33, 0.50, 120),
    ]
    keys = ("question_id", "label_set", "metric", "value", "ci_low", "ci_high", "n")
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


def fixture_tables(seed: int) -> dict[str, pa.Table]:
    from atlas.sitedata.tables import SITE_TABLES

    rng = np.random.default_rng(seed)
    evidence = _evidence(rng)
    cols = {
        "meta": _meta(),
        "coverage": _coverage(),
        "domain_share": _domain_share(rng),
        "evidence": evidence,
        "findings": _findings(),
        "finding_evidence": _finding_evidence(rng, evidence),
        "runs": _runs(),
        "quality": _quality(),
    }
    return {
        name: pa.Table.from_pydict(cols[name], schema=SITE_TABLES[name])
        for name in SITE_TABLES
    }


def write_fixtures(dir: Path, seed: int) -> None:
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    for name, table in fixture_tables(seed).items():
        pq.write_table(table, dir / f"{name}.parquet", compression="zstd")

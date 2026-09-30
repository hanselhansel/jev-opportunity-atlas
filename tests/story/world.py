"""Synthetic world for story tests: a snapshot, a phase-2 facet sample with
pos and neg phases, screen/facets/assign runs with ledgers, and the config
files ``atlas story data`` consumes. Comment ids are 9_000_000_000 and above;
no real HN text or usernames. Other story lanes reuse this world.

Population (240 pos rows, 20 neg rows):
- pos ids BASE..BASE+229 cycle 40 threads over periods P01..P11;
- pos ids BASE+230..BASE+239 are the thin period P12: 10 firsthand rows, all
  on card c01;
- every 13th pos row is ``secondhand_account`` (not a firsthand problem);
- card c04's rows all sit in one thread (STORY+7);
- i%9 pos rows are assigned group ``none`` (unplaced) and i%7 get
  ``card_p`` 0.3 (below the counting cutoff);
- neg rows carry facet answers including domains, two of them
  ``firsthand_account``, so the pos-only population rule is exercised.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.screen.unpack import SCREEN_BY_COMMENT

REPO = Path(__file__).resolve().parents[2]
BASE, STORY = 9_000_000_000, 9_500_000_000
TV = "t9"
SNAPSHOT, SAMPLE = "snap-syn", "facet-syn"
SCREEN_RUN, FACETS_RUN, ASSIGN_RUN = "screen-syn", "facets-syn", "assign-syn"
AUDIT_RUN, BENCH_RUN, PLANTED_RUN = "audit-syn", "bench-syn", "planted-syn"
BUILDERS_RUN = "builders-syn"
N_POS, N_P12, N_NEG = 230, 10, 20
DOMAINS = ("software_development", "infrastructure_ops", "health_medical")
ROLES = ("software_engineer", "manager", "founder_executive", "unclear")
PERIODS = [f"P{i:02d}" for i in range(1, 13)]

CARDSET_YAML = f"""taxonomy_version: {TV}
groups:
  g01: {{label: "Synthetic group one"}}
  g02: {{label: "Synthetic group two"}}
cards:
  - {{card_id: c01, group_id: g01, statement: "Synthetic need one", status: approved}}
  - {{card_id: c02, group_id: g01, statement: "Synthetic need two", status: approved}}
  - {{card_id: c03, group_id: g02, statement: "Synthetic need three", status: approved}}
  - {{card_id: c04, group_id: g02, statement: "Synthetic need four", status: approved}}
"""

LABELS_YAML = f"""taxonomy_version: {TV}
groups:
  g01: "Group one short"
  g02: "Group two short"
cards:
  c01: "Need one"
  c02: "Need two"
  c03: "Need three"
  c04: "Need four"
"""

RUN_PHASES = """[runs]
"screen-syn" = "screen"
"facets-syn" = "facets"
"assign-syn" = "assign"
"assign-syn/replies" = "replies"
"assign-syn/solutions" = "named fixes"
"audit-syn" = "checks"
"bench-syn" = "checks"
"planted-syn" = "checks"
"builders-syn" = "builders"
"""

ROBUST_SCREEN = {
    "main_run": SCREEN_RUN,
    "sample_id": "main-20260930b",
    "cutoff": 0.7,
    "n_sample": 3000,
    "runs": {
        SCREEN_RUN: {"n": 3000, "prevalence": 0.07, "ci_low": 0.06, "ci_high": 0.08},
        "robust-screen-para1": {
            "n": 2990,
            "prevalence": 0.06,
            "ci_low": 0.05,
            "ci_high": 0.07,
            "vs_main": {"n": 2990, "agreement": 0.97, "kappa": 0.9, "spearman": 0.99},
        },
        "robust-screen-para2": {
            "n": 2985,
            "prevalence": 0.08,
            "ci_low": 0.07,
            "ci_high": 0.09,
            "vs_main": {"n": 2985, "agreement": 0.96, "kappa": 0.88, "spearman": 0.99},
        },
    },
}

ROBUST_ASSIGN = {
    "main_run": ASSIGN_RUN,
    "version": TV,
    "n_main": 3000,
    "runs": {
        "robust-assign-para1": {
            "n": 2980,
            "n_common": 2970,
            "group_agreement": 0.91,
            "card_agreement": 0.84,
            "card_shares": {},
            "max_abs_diff": 0.01,
        },
        "robust-assign-para2": {
            "n": 2975,
            "n_common": 2960,
            "group_agreement": 0.9,
            "card_agreement": 0.83,
            "card_shares": {},
            "max_abs_diff": 0.012,
        },
    },
}


def _ledger(run_dir: Path, run_id: str, qs: str, n: int, rng) -> None:
    rows = []
    for i in range(n):
        rows.append(
            {
                "run_id": run_id,
                "logical_call_id": f"{run_id}-{i}",
                "attempt": 1,
                "comment_id": BASE + i,
                "question_set": qs,
                "started_at": f"2026-09-29T10:00:{i % 60:02d}+00:00",
                "ended_at": f"2026-09-29T10:01:{i % 60:02d}+00:00",
                "request_ms": float(rng.uniform(100, 900)),
                "http_status": 200,
                "cost_usd": 0.001,
                "cost_class": "calculated",
            }
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "ledger.jsonl").write_text(
        "".join(
            json.dumps({k: r.get(k) for k in contracts.LEDGER_FIELDS}) + "\n"
            for r in rows
        )
    )


def _answer(run_id, cid, qs, qid, qtype, noul=None, choice=None, score=None):
    return {
        "run_id": run_id,
        "comment_id": cid,
        "question_set": qs,
        "question_id": qid,
        "qtype": qtype,
        "noul": noul,
        "choice": choice,
        "score": score,
        "probabilities_json": None,
        "confidence": 0.8 if qtype == "choice" else None,
        "model_returned": "jev-synthetic",
        "request_id": f"r{cid}",
        "logical_call_id": f"l{cid}",
        "cache_hit": False,
    }


def _rows() -> tuple[list[dict], list[dict]]:
    # Weights mimic w1/p2: the pos draw is light, the neg check slice heavy.
    # The weighted firsthand/placed funnel counts then sit below ``screened``.
    pos = [
        {
            "comment_id": BASE + i,
            "story_id": STORY + (i % 40),
            "stratum": f"s{i % 3}",
            "period": f"P{i % 11 + 1:02d}",
            "author": f"u{i % 97}",
            "weight": 0.4 + (i % 5) * 0.1,
            "wave": 1 if i % 17 else 2,
        }
        for i in range(N_POS)
    ]
    pos += [
        {
            "comment_id": BASE + N_POS + i,
            "story_id": STORY + 30 + (i % 5),
            "stratum": f"s{i % 3}",
            "period": "P12",
            "author": f"u{200 + i}",
            "weight": 0.4,
            "wave": 1,
        }
        for i in range(N_P12)
    ]
    neg = [
        {
            "comment_id": BASE + 900 + i,
            "story_id": STORY + 35 + (i % 5),
            "stratum": f"s{(i + 1) % 3}",
            "period": f"P{i % 10 + 1:02d}",
            "author": f"u{300 + i}",
            "weight": 3.0 + (i % 7) * 0.5,
            "wave": 1,
        }
        for i in range(N_NEG)
    ]
    return pos, neg


def build_world(root: Path, monkeypatch) -> dict:
    """Write the synthetic world under ``root`` and point ``paths`` at it."""
    for name, rel in (
        ("SNAPSHOTS", "data/snapshots"),
        ("SAMPLES", "data/samples"),
        ("LABELS", "data/labels"),
        ("RUNS", "runs"),
        ("CONFIGS", "configs"),
        ("ROOT", "."),
    ):
        monkeypatch.setattr(paths, name, (root / rel).resolve())
    rng = np.random.default_rng(7)
    pos, neg = _rows()
    ids = [r["comment_id"] for r in pos + neg]
    by_id = {r["comment_id"]: r for r in pos + neg}

    cfg = root / "configs"
    (cfg / "cards").mkdir(parents=True)
    (cfg / "questions").mkdir()
    (cfg / "cards" / f"syn.{TV}.yaml").write_text(CARDSET_YAML)
    (cfg / "cards" / f"syn.{TV}.labels.yaml").write_text(LABELS_YAML)
    for f in ("questions/facets.v2.json", "tools.v1.yaml",
              "cards/planted.v1.yaml"):
        shutil.copy(REPO / "configs" / f, cfg / f)
    (cfg / "run_phases.toml").write_text(RUN_PHASES)

    snap = paths.snapshot_dir(SNAPSHOT)
    snap.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "id": pa.array(ids, pa.int64()),
                "author": [by_id[c]["author"] for c in ids],
                "story_id": pa.array([by_id[c]["story_id"] for c in ids], pa.int64()),
                "period": [by_id[c]["period"] for c in ids],
                "text_sha256": [
                    hashlib.sha256(f"s{c}".encode()).hexdigest() for c in ids
                ],
            }
        ),
        snap / "comments.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "dimension": "period",
                    "key": p,
                    "count": sum(r["period"] == p for r in pos + neg),
                }
                for p in PERIODS
            ]
            + [
                {"dimension": "state", "key": "ok", "count": len(ids)},
                {"dimension": "exclusion_reason", "key": "non_english", "count": 5},
            ],
            schema=contracts.COVERAGE,
        ),
        snap / "coverage.parquet",
    )
    (snap / "manifest.json").write_text(
        json.dumps(
            {
                "window": {
                    "start": "2025-09-28T00:00:00Z",
                    "end": "2026-09-28T00:00:00Z",
                },
                "counts": {"comments": 3990000, "eligible": 3680000},
            }
        )
    )

    screen = paths.run_dir(SCREEN_RUN)
    screen.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "comment_id": c,
                    "story_id": by_id[c]["story_id"],
                    "stratum": by_id[c]["stratum"],
                    "weight": 10.0,
                    "half": contracts.half_of(by_id[c]["story_id"]),
                    "firsthand_p": 0.9,
                    "packed_id": c,
                    "slot": "a",
                    "model_returned": "jev-synthetic",
                    "request_id": f"r{c}",
                }
                for c in ids
            ],
            schema=SCREEN_BY_COMMENT,
        ),
        screen / "screen_by_comment.parquet",
    )
    (screen / "screen.json").write_text(json.dumps({"sample_id": "main-20260930b"}))
    _ledger(screen, SCREEN_RUN, "screen-packed@1", 100, rng)

    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    sample_schema = pa.schema(
        [
            ("comment_id", pa.int64()),
            ("story_id", pa.int64()),
            ("stratum", pa.string()),
            ("half", pa.string()),
            ("phase", pa.string()),
            ("w1", pa.float64()),
            ("p2", pa.float64()),
            ("weight", pa.float64()),
            ("firsthand_p", pa.float64()),
            ("wave", pa.int8()),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "comment_id": r["comment_id"],
                    "story_id": r["story_id"],
                    "stratum": r["stratum"],
                    "half": contracts.half_of(r["story_id"]),
                    "phase": phase,
                    "w1": r["weight"],
                    "p2": 1.0,
                    "weight": r["weight"],
                    "firsthand_p": 0.9 if phase == "pos" else 0.2,
                    "wave": r["wave"],
                }
                for phase, rows in (("pos", pos), ("neg", neg))
                for r in rows
            ],
            schema=sample_schema,
        ),
        paths.sample_path(SAMPLE),
    )
    (paths.SAMPLES / f"{SAMPLE}.json").write_text(
        json.dumps(
            {
                "sample_id": SAMPLE,
                "parent_run": SCREEN_RUN,
                "snapshot_id": SNAPSHOT,
                "n_pos": len(pos),
                "n_neg": len(neg),
            }
        )
    )

    is_fh = {}
    for i, r in enumerate(pos):
        is_fh[r["comment_id"]] = i % 13 != 0 or i >= N_POS
    answers = []
    for i, r in enumerate(pos + neg):
        c = r["comment_id"]
        if i < len(pos):
            acct = "firsthand_account" if is_fh[c] else "secondhand_account"
            domain = DOMAINS[i % 3]
            role = ROLES[i % 4]
        else:
            acct = "firsthand_account" if i % 10 == 0 else "general_opinion"
            domain = DOMAINS[(i + 1) % 3]
            role = ROLES[(i + 1) % 4]
        answers += [
            _answer(FACETS_RUN, c, "facets@2", "account_type", "choice", choice=acct),
            _answer(FACETS_RUN, c, "facets@2", "domain", "choice", choice=domain),
            _answer(FACETS_RUN, c, "facets@2", "user_role", "choice", choice=role),
            _answer(FACETS_RUN, c, "facets@2", "severity", "score", score=i % 4),
            _answer(
                FACETS_RUN, c, "facets@2", "specificity", "score", score=(i + 1) % 4
            ),
        ]
        for j, q in enumerate(
            (
                "workaround",
                "cost_time",
                "cost_money",
                "cost_reliability",
                "cost_customers",
                "paid",
                "switched",
                "tried_alternatives",
                "abandoned",
            )
        ):
            answers.append(
                _answer(FACETS_RUN, c, "facets@2", q, "noul", noul=(i + j) % 2 * 0.8)
            )
    facets = paths.run_dir(FACETS_RUN)
    (facets / "answers").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(answers, schema=contracts.ANSWERS),
        facets / "answers" / "part-0.parquet",
    )
    _ledger(facets, FACETS_RUN, "facets@2", 80, rng)

    assign_rows = []
    for i, r in enumerate(pos):
        c = r["comment_id"]
        if i >= N_POS:
            group, card, card_p = "g01", "c01", 0.9
        elif i % 9 == 0:
            group, card, card_p = "none", None, None
        elif by_id[c]["story_id"] == STORY + 7:
            group, card, card_p = "g02", "c04", 0.9
        elif i % 7 == 0:
            group, card, card_p = "g01", "c02", 0.3
        else:
            card = ("c01", "c02", "c03")[i % 3]
            group = "g01" if card in ("c01", "c02") else "g02"
            card_p = 0.9
        assign_rows.append(
            {
                "run_id": ASSIGN_RUN,
                "comment_id": c,
                "taxonomy_version": TV,
                "group_id": group,
                "group_p": 0.9,
                "group_confidence": 0.9,
                "card_id": card,
                "card_p": card_p,
                "card_confidence": 0.9,
                "verified_p": 0.9,
            }
        )
    assign = paths.run_dir(ASSIGN_RUN)
    assign.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(assign_rows, schema=contracts.ASSIGNMENTS),
        assign / f"assignments-{TV}.parquet",
    )
    _ledger(assign, ASSIGN_RUN, f"assign-g@{TV}", 40, rng)
    _ledger(assign / "replies", f"{ASSIGN_RUN}/replies", "reply@1", 12, rng)
    _ledger(
        assign / "solutions",
        f"{ASSIGN_RUN}/solutions",
        "solutions@1",
        8,
        rng,
    )
    _ledger(paths.run_dir(BUILDERS_RUN), BUILDERS_RUN, "builders@1", 10, rng)

    audit = paths.run_dir(AUDIT_RUN)
    _ledger(audit, AUDIT_RUN, f"assign-g@{TV}", 30, rng)
    (audit / "eval_assignment_audit.json").write_text(
        json.dumps(
            {
                "label_set": "assignment_audit",
                "groups": {
                    "jev": {
                        "n": 90,
                        "n_unsure": 4,
                        "strict": {"precision": 0.81, "ci": [0.72, 0.88]},
                        "lenient": {"precision": 0.9, "ci": [0.83, 0.95]},
                    },
                    "random": {
                        "n": 30,
                        "n_unsure": 1,
                        "strict": {"precision": 0.12, "ci": [0.03, 0.25]},
                        "lenient": {"precision": 0.2, "ci": [0.08, 0.35]},
                    },
                },
            }
        )
    )
    bench = paths.run_dir(BENCH_RUN)
    _ledger(bench, BENCH_RUN, "screen@1", 20, rng)
    (bench / "benchmark_score.json").write_text(
        json.dumps(
            {
                "n_cases": 60,
                "firsthand": {
                    "single": {"0.5": {"n": 60, "accuracy": 0.9}},
                    "packed": {"0.5": {"n": 60, "accuracy": 0.85}},
                },
            }
        )
    )
    (paths.RUNS / "robust-screen-compare.json").write_text(
        json.dumps(ROBUST_SCREEN)
    )
    (paths.RUNS / "robust-assign-compare.json").write_text(json.dumps(ROBUST_ASSIGN))

    # A planted run: every planted comment lands on its card, decoys get none.
    import yaml

    planted_cfg = yaml.safe_load(
        (cfg / "cards" / "planted.v1.yaml").read_text()
    )
    pgroup = {
        c["card_id"]: c["group_id"] for c in planted_cfg["cards"]
    }
    prows = [
        {
            "run_id": PLANTED_RUN,
            "comment_id": c["comment_id"],
            "taxonomy_version": f"{TV}+planted-v1",
            "group_id": pgroup[c["card_id"]],
            "group_p": 0.9,
            "group_confidence": 0.9,
            "card_id": c["card_id"],
            "card_p": 0.9,
            "card_confidence": 0.9,
            "verified_p": 0.9,
        }
        for c in planted_cfg["planted"]
    ] + [
        {
            "run_id": PLANTED_RUN,
            "comment_id": d["comment_id"],
            "taxonomy_version": f"{TV}+planted-v1",
            "group_id": "none",
            "group_p": 0.9,
            "group_confidence": 0.9,
            "card_id": "none",
            "card_p": None,
            "card_confidence": 0.9,
            "verified_p": 0.9,
        }
        for d in planted_cfg["decoys"]
    ]
    planted = paths.run_dir(PLANTED_RUN)
    planted.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(prows, schema=contracts.ASSIGNMENTS),
        planted / f"assignments-{TV}+planted-v1.parquet",
    )
    _ledger(planted, PLANTED_RUN, f"assign-g@{TV}", 6, rng)
    return {
        "ids": ids,
        "pos": [r["comment_id"] for r in pos],
        "neg": [r["comment_id"] for r in neg],
        "p12": [r["comment_id"] for r in pos if r["period"] == "P12"],
        "firsthand": sorted(c for c, v in is_fh.items() if v),
        "by_id": by_id,
        "snapshot": SNAPSHOT,
        "sample": SAMPLE,
    }

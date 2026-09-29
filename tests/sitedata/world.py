"""Synthetic world for site-data tests: 600 sampled comments in 60 threads,
ids 9_000_000_000+, a screen run, a facets run, an assign run with an audit
evaluation, a benchmark run, and calibration gold labels drawn at a known rate.
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
N, N_STORIES = 600, 60
DOMAINS = ("software_development", "infrastructure_ops", "data_ml_ai")
CARDS = ("c01", "c02", "c03", "c04")
TV = "t9"
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


def _ledger(run_dir: Path, run_id: str, qs: str, n: int, rng) -> None:
    rows = []
    for i in range(n):
        attempts = 2 if i % 10 == 0 else 1
        for a in range(1, attempts + 1):
            ok = a == attempts
            rows.append(
                {
                    "run_id": run_id,
                    "logical_call_id": f"{run_id}-{i}",
                    "attempt": a,
                    "comment_id": BASE + i,
                    "question_set": qs,
                    "started_at": f"2026-09-29T10:00:{i % 60:02d}+00:00",
                    "ended_at": f"2026-09-29T10:{1 + i % 5:02d}:00+00:00",
                    "request_ms": float(rng.uniform(100, 900)),
                    "http_status": 200 if ok else 500,
                    "cost_usd": 0.001 if ok else None,
                    "cost_class": "calculated" if ok else "unknown",
                }
            )
    rows.append(
        {
            **rows[0],
            "attempt": 0,
            "cost_class": "replay",
            "cost_usd": 0.0,
            "http_status": None,
        }
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "ledger.jsonl").write_text(
        "".join(
            json.dumps({k: r.get(k) for k in contracts.LEDGER_FIELDS}) + "\n"
            for r in rows
        )
    )


def _answer(
    run_id, cid, qs, qid, qtype, noul=None, choice=None, score=None, probs=None
):
    return {
        "run_id": run_id,
        "comment_id": cid,
        "question_set": qs,
        "question_id": qid,
        "qtype": qtype,
        "noul": noul,
        "choice": choice,
        "score": score,
        "probabilities_json": json.dumps(probs) if probs else None,
        "confidence": 0.8 if qtype == "choice" else None,
        "model_returned": "jev-synthetic",
        "request_id": f"r{cid}",
        "logical_call_id": f"l{cid}",
        "cache_hit": False,
    }


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
    (root / "configs" / "cards").mkdir(parents=True)
    for f in ("ranking.toml", "finding_criteria.toml"):
        shutil.copy(REPO / "configs" / f, root / "configs" / f)
    (root / "configs" / "cards" / f"syn.{TV}.yaml").write_text(CARDSET_YAML)
    rng = np.random.default_rng(7)
    ids = [BASE + i for i in range(N)]
    story = {c: STORY + (i % N_STORIES) for i, c in enumerate(ids)}
    period = {c: f"P{i % 12 + 1:02d}" for i, c in enumerate(ids)}

    snap = paths.snapshot_dir("snap-syn")
    snap.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "id": pa.array(ids, pa.int64()),
                "author": [f"u{i % 150}" for i in range(N)],
                "story_id": pa.array([story[c] for c in ids], pa.int64()),
                "period": [period[c] for c in ids],
                "thread_type": ["ask_hn" if i % 4 == 0 else "story" for i in range(N)],
                "text_norm": [f"synthetic comment body number {i}" for i in range(N)],
                "text_sha256": [
                    hashlib.sha256(f"s{c}".encode()).hexdigest() for c in ids
                ],
            }
        ),
        snap / "comments.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "dimension": ["state", "period"],
                "key": ["ok", "P01"],
                "count": pa.array([N, 50], pa.int64()),
            },
            schema=contracts.COVERAGE,
        ),
        snap / "coverage.parquet",
    )
    (snap / "manifest.json").write_text(
        json.dumps(
            {"window": {"start": "2025-09-28T00:00:00Z", "end": "2026-09-28T00:00:00Z"}}
        )
    )

    fh = {c: (0.9 if i % 5 else 0.1) for i, c in enumerate(ids)}
    screen = paths.run_dir("screen-syn")
    screen.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "comment_id": c,
                    "story_id": story[c],
                    "stratum": f"s{i % 2}",
                    "weight": 10.0 + (i % 2) * 5,
                    "half": contracts.half_of(story[c]),
                    "firsthand_p": fh[c],
                    "packed_id": c,
                    "slot": "a",
                    "model_returned": "jev-synthetic",
                    "request_id": f"r{c}",
                }
                for i, c in enumerate(ids)
            ],
            schema=SCREEN_BY_COMMENT,
        ),
        screen / "screen_by_comment.parquet",
    )
    (screen / "screen.json").write_text(json.dumps({"sample_id": "sample-syn"}))
    _ledger(screen, "screen-syn", "screen-packed@1", 120, rng)

    # Phase-2 facet sample: pos rows are the screen-positive draw (p2 = 0.5, so
    # weight = 2 * w1), plus a 24-comment neg check slice (p2 = 0.05, so
    # weight = 20 * w1). weight = w1 / p2, never the screen weight w1.
    pos = [c for c in ids if fh[c] >= 0.7]
    neg = [c for c in ids if fh[c] < 0.5][:24]
    faceted = pos + neg
    pos_set, neg_set = set(pos), set(neg)
    p2 = {"pos": 0.5, "neg": 0.05}
    idx = {c: i for i, c in enumerate(ids)}
    facet = {}
    for c in faceted:
        phase = "pos" if c in pos_set else "neg"
        w1 = 10.0 + (idx[c] % 2) * 5
        facet[c] = {
            "comment_id": c,
            "story_id": story[c],
            "stratum": f"s{idx[c] % 2}",
            "half": contracts.half_of(story[c]),
            "phase": phase,
            "w1": w1,
            "p2": p2[phase],
            "weight": w1 / p2[phase],
            "firsthand_p": fh[c],
        }
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            list(facet.values()),
            schema=pa.schema(
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
                ]
            ),
        ),
        paths.sample_path("facet-syn"),
    )
    # Every 13th pos comment is faceted but not a firsthand account: it must not
    # count as a firsthand problem anywhere.
    pos_idx = {c: i for i, c in enumerate(pos)}
    account = {
        c: (
            "secondhand_account"
            if c in pos_set and pos_idx[c] % 13 == 0
            else "firsthand_account"
        )
        for c in faceted
    }
    secondhand = {c for c in pos_set if account[c] != "firsthand_account"}
    domain = {c: DOMAINS[i % 3] for i, c in enumerate(faceted)}
    rows = []
    for i, c in enumerate(faceted):
        probs = {d: (0.8 if d == domain[c] else 0.1) for d in DOMAINS}
        rows += [
            _answer(
                "facets-syn",
                c,
                "facets@2",
                "domain",
                "choice",
                choice=domain[c],
                probs=probs,
            ),
            _answer(
                "facets-syn",
                c,
                "facets@2",
                "account_type",
                "choice",
                choice=account[c],
            ),
            _answer(
                "facets-syn",
                c,
                "facets@2",
                "pain_sentence",
                "choice",
                choice=f"s{i % 3}",
            ),
            _answer(
                "facets-syn",
                c,
                "facets@2",
                "user_role",
                "choice",
                choice=("software_engineer", "manager")[i % 2],
            ),
            _answer(
                "facets-syn", c, "facets@2", "resolution", "choice", choice="unresolved"
            ),
            _answer(
                "facets-syn", c, "facets@2", "specificity", "score", score=float(i % 4)
            ),
        ]
        for q in (
            "workaround",
            "cost_time",
            "cost_money",
            "paid",
            "switched",
            "abandoned",
        ):
            rows.append(
                _answer(
                    "facets-syn", c, "facets@2", q, "noul", noul=float(rng.uniform())
                )
            )
    facets = paths.run_dir("facets-syn")
    (facets / "answers").mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ANSWERS),
        facets / "answers" / "part-0.parquet",
    )
    _ledger(facets, "facets-syn", "facets@2", 80, rng)

    # c04 is engineered so every pos comment on story STORY+7 (and only those)
    # lands on it: one card whose items all sit in a single thread.
    assign_rows = []
    for i, c in enumerate(faceted):
        if story[c] == STORY + 7:
            card = "c04"
        else:
            card = CARDS[i % 4] if i % 9 else "none"
            if card == "c04":
                card = "c01"
        assign_rows.append(
            {
                "run_id": "assign-syn",
                "comment_id": c,
                "taxonomy_version": TV,
                "group_id": "g01" if card in ("c01", "c02") else "g02",
                "group_p": 0.9,
                "group_confidence": 0.9,
                "card_id": card,
                "card_p": 0.9,
                "card_confidence": 0.9,
                "verified_p": 0.2 if i % 11 == 0 else 0.9,
            }
        )
    run = paths.run_dir("assign-syn")
    run.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(assign_rows, schema=contracts.ASSIGNMENTS),
        run / f"assignments-{TV}.parquet",
    )
    _ledger(run, "assign-syn", f"assign-g@{TV}", 40, rng)
    (run / "eval_assignment_audit.json").write_text(
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
    bench = paths.run_dir("bench-syn")
    bench.mkdir(parents=True)
    (bench / "benchmark_score.json").write_text(
        json.dumps(
            {
                "n_cases": 60,
                "firsthand": {
                    "single": {"0.5": {"n": 60, "accuracy": 0.9}},
                    "packed": {"0.5": {"n": 60, "accuracy": 0.85}},
                },
                "account_type": {"n": 60, "accuracy": 0.7},
                "facets": {"workaround": {"n": 20, "accuracy": 0.75}},
                "cards": {"n": 30, "top1_accuracy": 0.6},
            }
        )
    )
    _ledger(bench, "bench-syn", "screen@1", 20, rng)

    gold = ids[::4]  # every 4th sampled comment, drawn at a known rate
    paths.LABELS.mkdir(parents=True)
    labels = []
    for c in gold:
        yes = fh[c] >= 0.5 and c % 7 != 0
        labels.append(
            {
                "label_id": f"L{c}f",
                "comment_id": c,
                "label_set": "calibration",
                "question_id": "firsthand_problem",
                "value": "yes" if yes else "no",
            }
        )
        if yes:
            labels.append(
                {
                    "label_id": f"L{c}d",
                    "comment_id": c,
                    "label_set": "calibration",
                    "question_id": "domain",
                    "value": domain[c],
                }
            )
    (paths.LABELS / "labels.jsonl").write_text(
        "".join(
            json.dumps({**r, "rubric_version": "v1", "reviewer": "x"}) + "\n"
            for r in labels
        )
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "label_set": "calibration",
                    "comment_id": c,
                    "draw_stratum": "u",
                    "selection_prob": 0.25,
                    "seed": 1,
                    "purpose": "calibration",
                }
                for c in gold
            ],
            schema=contracts.GOLD_DRAWS,
        ),
        paths.LABELS / "gold_draws.parquet",
    )
    return {
        "ids": ids,
        "faceted": pos,
        "pos": pos,
        "neg": neg,
        "facet": facet,
        "account": account,
        "secondhand": secondhand,
        "domain": domain,
        "gold": gold,
        "period": period,
        "story": story,
    }


def build(out: Path, label_sets=("calibration",), **kw):
    from atlas.sitedata.build import build_site_data

    return build_site_data(
        out,
        "snap-syn",
        "screen-syn",
        "facets-syn",
        "assign-syn",
        TV,
        list(label_sets),
        benchmark_run="bench-syn",
        facet_sample="facet-syn",
        n_boot=200,
        built_at="2026-09-29T12:00:00Z",
        **kw,
    )


def read(out: Path, name: str) -> list[dict]:
    return pq.read_table(out / f"{name}.parquet").to_pylist()

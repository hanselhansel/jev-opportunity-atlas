"""Shared synthetic world for the L16 mode tests (queue, UI, CLI).

Helpers only; no test functions. Each test module wraps ``make_env`` in its
own fixture so pytest can bind ``tmp_path``/``monkeypatch``.
"""

import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from atlas import contracts, paths

REPO = Path(__file__).resolve().parents[2]

BASE = 9_000_000_000

CARDSET = {
    "taxonomy_version": "t9",
    "groups": {
        "g01": {"label": "Synthetic group one"},
        "g02": {"label": "Synthetic group two"},
    },
    "cards": [
        {"card_id": "c0001", "group_id": "g01",
         "statement": "Synthetic need alpha", "status": "approved"},
        {"card_id": "c0002", "group_id": "g01",
         "statement": "Synthetic need beta", "status": "approved"},
        {"card_id": "c0003", "group_id": "g01",
         "statement": "Synthetic need gamma", "status": "approved"},
        {"card_id": "c0004", "group_id": "g01",
         "statement": "Synthetic need delta", "status": "approved"},
        {"card_id": "c0005", "group_id": "g02",
         "statement": "Synthetic need solo", "status": "approved"},
        {"card_id": "c0006", "group_id": "g01",
         "statement": "Synthetic need retired", "status": "retired"},
    ],
}


def make_env(tmp_path, monkeypatch):
    """Tmp CONFIGS (synth cardset + approved rubric + acquisition snapshot id)
    and tmp RUNS/LABELS."""
    configs = tmp_path / "configs"
    cards_dir = configs / "cards"
    cards_dir.mkdir(parents=True)
    (cards_dir / "synth.t9.yaml").write_text(yaml.safe_dump(CARDSET))
    (configs / "rubric.v1.md").write_text(
        "---\nversion: v1\nstatus: approved\n---\n\n# test rubric\n",
        encoding="utf-8",
    )
    (configs / "acquisition.toml").write_text(
        'snapshot_id = "snap-test"\n', encoding="utf-8"
    )
    questions = configs / "questions"
    questions.mkdir(exist_ok=True)
    shutil.copy(REPO / "configs" / "questions" / "screen.v0.json", questions)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "LABELS", tmp_path / "labels")
    monkeypatch.setattr(paths, "CONFIGS", configs)
    return tmp_path


def write_answers(run_id, part, comment_ids, nouls,
                  question_id="workaround", question_set="facets@1"):
    n = len(comment_ids)
    rows = {
        "run_id": [run_id] * n,
        "comment_id": comment_ids,
        "question_set": [question_set] * n,
        "question_id": [question_id] * n,
        "qtype": ["noul"] * n,
        "noul": nouls,
        "choice": [None] * n,
        "score": [None] * n,
        "probabilities_json": [None] * n,
        "confidence": [None] * n,
        "model_returned": ["m-test"] * n,
        "request_id": ["req"] * n,
        "logical_call_id": ["lc"] * n,
        "cache_hit": [False] * n,
    }
    directory = paths.run_dir(run_id) / "answers"
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(rows, schema=contracts.ANSWERS),
        directory / f"part-{part}.parquet",
    )


def assignment_row(cid, group, card, card_confidence, run_id="arun"):
    return {
        "run_id": run_id,
        "comment_id": cid,
        "taxonomy_version": "t9",
        "group_id": group,
        "group_p": 0.9,
        "group_confidence": 0.9,
        "card_id": card,
        "card_p": 0.8 if card not in (None, "none") else None,
        "card_confidence": card_confidence,
        "verified_p": None,
    }


def write_assignments(run_id, version, rows):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / f"assignments-{version}.parquet",
    )


def write_pain(run_id, pairs):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [{"comment_id": c, "pain_sentence": t} for c, t in pairs],
            schema=pa.schema(
                [("comment_id", pa.int64()), ("pain_sentence", pa.string())]
            ),
        ),
        run_dir / "pain.parquet",
    )


def write_merge_cardset(tmp_path, n_cards=14):
    """A single-group cardset large enough for a 50-item merge queue."""
    data = {
        "taxonomy_version": "t9",
        "groups": {"g01": {"label": "Merge group"}},
        "cards": [
            {"card_id": f"c{i:04d}", "group_id": "g01",
             "statement": f"Synthetic merge need {i}", "status": "approved"}
            for i in range(1, n_cards + 1)
        ],
    }
    (tmp_path / "configs" / "cards" / "mergey.t9.yaml").write_text(
        yaml.safe_dump(data)
    )


def metrics_table(with_score=True):
    cols = {
        "card_id": ["c0001", "c0002", "c0003", "c0004", "c0005",
                    "c0006", "c0099"],
        "n_authors": [10, 20, 30, 40, 50, 60, 70],
        "n_threads": [1, 2, 3, 4, 5, 6, 7],
        "n_periods": [1, 1, 2, 2, 3, 3, 4],
        "n_domains": [1, 2, 1, 2, 1, 2, 1],
    }
    if with_score:
        cols["score"] = [0.9, 0.7, 0.8, 0.6, 0.5, 1.0, 0.95]
    return pa.table(cols)


def gold_rows():
    return pq.read_table(paths.LABELS / "gold_draws.parquet").to_pylist()


def assignment_world(run_id):
    """~600 assignment rows: g01 (multi-card) and g02 (single card), both
    confidence bands, plus rows that must never be drawn."""
    rows = []
    cards = ["c0001", "c0002", "c0003", "c0004"]
    for i in range(300):  # g01: 150 high-confidence, 150 low
        rows.append(assignment_row(
            BASE + i, "g01", cards[i % 4], 0.9 if i < 150 else 0.2
        ))
    for i in range(300):  # g02: one active card only, both bands
        rows.append(assignment_row(
            BASE + 300 + i, "g02", "c0005", 0.85 if i < 150 else 0.25
        ))
    junk_ids = [BASE + 600 + i for i in range(6)]
    rows += [
        assignment_row(junk_ids[0], "g01", "none", 0.9),
        assignment_row(junk_ids[1], "none", None, None),
        assignment_row(junk_ids[2], "g01", "c0006", 0.9),   # retired card
        assignment_row(junk_ids[3], "g01", "c0001", None),  # no confidence
        assignment_row(junk_ids[4], "g01", "c0099", 0.9),   # unknown card
        assignment_row(junk_ids[5], "g01", "c0001", 0.9),   # no pain text
    ]
    write_assignments(run_id, "t9", rows)
    pain = {
        c: f"synthetic pain sentence for {c}"
        for c in list(range(BASE, BASE + 600)) + junk_ids[:5]
    }
    write_pain(run_id, sorted(pain.items()))
    return junk_ids, pain

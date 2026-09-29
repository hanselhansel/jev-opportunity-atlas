"""Shared helpers for benchmark tests: tmp configs carrying a tiny synthetic
cases file plus the real pilot.t1 cardset, and writers for hand-built run
directories (answers parts, packed map, benchmark.json)."""

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from atlas import contracts, paths

ROOT = Path(__file__).resolve().parents[2]


def bench_configs(pilot_repo, cases: dict):
    """On top of pilot_repo: copy the real pilot.t1 cardset and write
    `cases` as configs/benchmark/cases.v1.yaml."""
    configs = paths.CONFIGS
    (configs / "cards").mkdir(exist_ok=True)
    shutil.copy(
        ROOT / "configs" / "cards" / "pilot.t1.yaml",
        configs / "cards" / "pilot.t1.yaml",
    )
    (configs / "benchmark").mkdir(exist_ok=True)
    (configs / "benchmark" / "cases.v1.yaml").write_text(
        yaml.safe_dump(cases), encoding="utf-8"
    )
    return pilot_repo


def answer_row(
    run_id,
    cid,
    question_set,
    question_id,
    noul=None,
    choice=None,
    probs=None,
    confidence=None,
):
    """One contract ANSWERS row."""
    return {
        "run_id": run_id,
        "comment_id": cid,
        "question_set": question_set,
        "question_id": question_id,
        "qtype": "choice" if choice is not None else "noul",
        "noul": noul,
        "choice": choice,
        "score": None,
        "probabilities_json": json.dumps(probs) if probs else None,
        "confidence": confidence,
        "model_returned": "jev-1.13.0",
        "request_id": f"req-{cid}",
        "logical_call_id": f"lc-{cid}-{question_id}",
        "cache_hit": False,
    }


def write_answers(run_id, rows, part=0):
    directory = paths.run_dir(run_id) / "answers"
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ANSWERS),
        directory / f"part-{part}.parquet",
    )


def write_benchmark_json(run_id, version="v1", n_cases=0, budget="discovery"):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    from atlas.benchmark.run import cases_sha256

    meta = {
        "cases_version": version,
        "cases_sha256": cases_sha256(version),
        "n_cases": n_cases,
        "cardset": "pilot.t1",
        "pack_k": 5,
        "budget": budget,
    }
    (run_dir / "benchmark.json").write_text(
        json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return meta

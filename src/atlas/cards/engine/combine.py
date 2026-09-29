"""Combine several assign runs of one taxonomy version into a new run (L28).

The main run assigns comments in waves: one `cards induce` run for wave 1 and
a `cards assign` run for wave 2, both under the same cardset version.
Downstream commands (`site data`, `cards verify`, `cards merge`,
`cards replies`, `robust compare-assign`) read exactly one run, so
`cards combine` merges them: every input's `assignments-<version>.parquet` is
read through load_assignments, run_id is re-stamped to the output run, rows
are sorted by comment_id, each run's `pain.parquet` is concatenated
(deduplicated by comment_id), and a `combine-<version>.json` sidecar records
the input run ids, per-run row counts, and each input's sha256.

`answers/` directories are not copied: verify, merge, and replies write their
own answers into the run they are pointed at, so nothing downstream needs the
inputs' raw answers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.cards.engine.assign import (
    AssignResult,
    assignments_path,
    load_assignments,
    write_assignments,
)

PAIN_SCHEMA = pa.schema(
    [("comment_id", pa.int64()), ("pain_sentence", pa.string())]
)


class CombineError(ValueError):
    pass


def combine_path(run_dir: Path, version: str) -> Path:
    return Path(run_dir) / f"combine-{version}.json"


def combine(run_ids, version: str, out_run: str) -> dict:
    """Merge assign runs `run_ids` (all on taxonomy `version`) into `out_run`."""
    run_ids = [str(r) for r in run_ids]
    if not run_ids:
        raise CombineError("combine needs at least one input run")
    if out_run in run_ids:
        raise CombineError(f"output run {out_run!r} is also an input run")

    rows: list[dict] = []
    meta: dict[int, dict] = {}
    pain: dict[int, str] = {}
    seen: set[int] = set()
    inputs = []
    for rid in run_ids:
        run_dir = paths.run_dir(rid)
        path = assignments_path(run_dir, version)
        if not path.exists():
            raise CombineError(f"run {rid} has no {path.name}")
        result = load_assignments(run_dir, version)
        inputs.append(
            {
                "run_id": rid,
                "rows": len(result.rows),
                "assignments_sha256": hashlib.sha256(
                    path.read_bytes()
                ).hexdigest(),
            }
        )
        for r in result.rows:
            cid = r["comment_id"]
            if r["taxonomy_version"] != version:
                raise CombineError(
                    f"run {rid} comment {cid} carries taxonomy_version "
                    f"{r['taxonomy_version']!r}, expected {version!r}"
                )
            if cid in seen:
                raise CombineError(
                    f"comment_id {cid} is assigned by more than one input run"
                )
            seen.add(cid)
            rows.append({**r, "run_id": out_run})
            if cid in result.meta:
                meta[cid] = result.meta[cid]
        pain_path = run_dir / "pain.parquet"
        if not pain_path.exists():
            raise CombineError(f"{pain_path} missing: run {rid} is incomplete")
        for p in pq.read_table(pain_path).to_pylist():
            cid = p["comment_id"]
            if cid in pain and pain[cid] != p["pain_sentence"]:
                raise CombineError(
                    f"runs disagree on the pain sentence for comment {cid}"
                )
            pain[cid] = p["pain_sentence"]

    rows.sort(key=lambda r: r["comment_id"])
    out_dir = paths.run_dir(out_run)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_assignments(out_dir, AssignResult(rows=rows, meta=meta), version)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"comment_id": c, "pain_sentence": pain[c]}
                for c in sorted(pain)
            ],
            schema=PAIN_SCHEMA,
        ),
        str(out_dir / "pain.parquet"),
    )
    sidecar = {
        "run_id": out_run,
        "taxonomy_version": version,
        "source_runs": inputs,
    }
    combine_path(out_dir, version).write_text(
        json.dumps(sidecar, indent=1) + "\n", encoding="utf-8"
    )
    return sidecar

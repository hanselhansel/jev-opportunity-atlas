"""Run-directory I/O for the batch runner: manifest, done.jsonl, answer parts.

Crash-safety rules (A6): parts are written to `part-<seq>.parquet.tmp`, fsynced,
then renamed; done rows are appended only after the rename; a done row whose
part is missing is dropped so the item is redone.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.inference.questions import canonical_json


class ManifestMismatch(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=paths.ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def ensure_manifest(ctx, qs) -> None:
    """Write run_manifest.json on first use of the run dir; on later runs, append
    a new question set and refuse a different model or a changed set hash."""
    path = ctx.run_dir / "run_manifest.json"
    entry = {"label": qs.label, "file_sha256": qs.sha256}
    if not path.exists():
        _atomic_write_json(
            path,
            {
                "run_id": ctx.run_id,
                "model": ctx.model,
                "question_sets": [entry],
                "price_version": ctx.price_version,
                "cap_usd": ctx.guard.cap_usd,
                "budget": ctx.budget,
                "git_commit": _git_commit(),
                "started_at": _utcnow(),
            },
        )
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("model") != ctx.model:
        raise ManifestMismatch(
            f"{path}: model is {manifest.get('model')!r}, run wants {ctx.model!r}"
        )
    known = {e["label"]: e for e in manifest.get("question_sets", [])}
    if qs.label in known:
        if known[qs.label].get("file_sha256") != qs.sha256:
            raise ManifestMismatch(
                f"{path}: question set {qs.label} hash changed"
            )
        return
    manifest.setdefault("question_sets", []).append(entry)
    _atomic_write_json(path, manifest)


def load_done(run_dir: Path, question_set: str) -> set:
    """Comment ids already completed for this question set. A done row whose
    answer part is gone is dropped (the item is redone)."""
    done: set = set()
    path = run_dir / "done.jsonl"
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("question_set") != question_set:
            continue
        if (run_dir / "answers" / f"part-{row['part']}.parquet").exists():
            done.add(row["comment_id"])
    return done


def append_done(run_dir: Path, entries: list[dict]) -> None:
    path = run_dir / "done.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
        fh.flush()
        os.fsync(fh.fileno())


def answer_rows(
    run_id: str,
    comment_id: int,
    question_set: str,
    questions: dict,
    answers: dict,
    model_returned: str | None,
    request_id: str | None,
    logical_call_id: str,
    cache_hit: bool,
) -> list[dict]:
    """One ANSWERS row per question, in question order."""
    rows = []
    for qid, q in questions.items():
        a = answers.get(qid) or {}
        probs = a.get("probabilities")
        rows.append(
            {
                "run_id": run_id,
                "comment_id": comment_id,
                "question_set": question_set,
                "question_id": qid,
                "qtype": q.get("type"),
                "noul": a.get("noul"),
                "choice": a.get("choice"),
                "score": a.get("score"),
                "probabilities_json": canonical_json(probs)
                if probs is not None
                else None,
                "confidence": a.get("confidence"),
                "model_returned": model_returned,
                "request_id": request_id,
                "logical_call_id": logical_call_id,
                "cache_hit": cache_hit,
            }
        )
    return rows


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class PartExists(RuntimeError):
    pass


def write_part(run_dir: Path, rows: list[dict]) -> int:
    """Write `answers/part-<seq>.parquet` atomically; seq = 1 + max existing.
    Parts are never overwritten."""
    answers_dir = run_dir / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    for stale in answers_dir.glob("part-*.parquet.tmp"):
        stale.unlink()  # crash leftovers; only *.parquet may remain
    seqs = [
        int(p.stem.rsplit("-", 1)[1]) for p in answers_dir.glob("part-*.parquet")
    ]
    seq = 1 + max(seqs, default=0)
    tmp = answers_dir / f"part-{seq}.parquet.tmp"
    final = answers_dir / f"part-{seq}.parquet"
    if final.exists():
        raise PartExists(f"{final} already exists")
    table = pa.Table.from_pylist(rows, schema=contracts.ANSWERS)
    pq.write_table(table, str(tmp))
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if final.exists():
        raise PartExists(f"{final} already exists")
    os.rename(tmp, final)
    _fsync_dir(answers_dir)
    return seq

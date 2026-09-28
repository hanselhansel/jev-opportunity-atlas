"""Release staging: copy the allowlisted slice of a snapshot, runs, samples,
labels, and reproducibility inputs into exports/<release>, then gate, hash, and
manifest it. A blocked release leaves nothing behind in exports/."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts
from atlas.publication.allowlist import (
    EXTRA,
    LABEL_DROP,
    RUN_FILES,
    SNAPSHOT_FILES,
    scan_release,
    text_gate,
)


class ExportError(Exception):
    pass


def _copy_columns(src: Path, dest: Path, columns: tuple[str, ...]) -> None:
    pf = pq.ParquetFile(src)
    present = [c for c in columns if c in pf.schema_arrow.names]
    schema = pa.schema([pf.schema_arrow.field(c) for c in present])
    with pq.ParquetWriter(dest, schema, compression="zstd") as writer:
        for batch in pf.iter_batches(batch_size=65536, columns=present):
            writer.write_table(pa.Table.from_batches([batch], schema=schema))


def _stage_snapshot(root: Path, tmp: Path, snapshot_id: str) -> None:
    src = root / "data" / "snapshots" / snapshot_id
    if not src.is_dir() or not (src / "comments.parquet").exists():
        raise ExportError(f"snapshot {snapshot_id} not found or incomplete")
    dest = tmp / "snapshot"
    dest.mkdir()
    for name, columns in SNAPSHOT_FILES.items():
        sp = src / name
        if not sp.exists():
            continue
        if columns is None:
            shutil.copy2(sp, dest / name)
        else:
            _copy_columns(sp, dest / f"{sp.stem}_public.parquet", columns)
    manifest = src / "manifest.json"
    if manifest.exists():
        shutil.copy2(manifest, dest / "manifest.json")


def _stage_runs(root: Path, tmp: Path, run_ids: list[str]) -> None:
    for rid in run_ids:
        rd = root / "runs" / rid
        if not rd.is_dir():
            raise ExportError(f"run {rid} not found")
        for pattern in RUN_FILES:
            for f in sorted(rd.glob(pattern)):
                if f.is_file():
                    rel = f.relative_to(rd)
                    dest = tmp / "runs" / rid / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)


def _stage_samples(root: Path, tmp: Path) -> None:
    src = root / "data" / "samples"
    if not src.is_dir():
        return
    for f in sorted(src.iterdir()):
        if f.is_file() and f.suffix in (".parquet", ".json"):
            dest = tmp / "samples" / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)


def _stage_labels(root: Path, tmp: Path) -> None:
    src = root / "data" / "labels"
    if not src.is_dir():
        return
    fields = [f for f in contracts.LABELS if f.name not in LABEL_DROP]
    names = [f.name for f in fields]
    latest: dict[tuple, dict] = {}
    for f in sorted(src.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = (
                row.get("label_set"),
                row.get("comment_id"),
                row.get("question_id"),
            )
            latest[key] = {k: row.get(k) for k in names}
    if not latest:
        return
    schema = pa.schema(fields)
    table = pa.table(
        {
            f.name: pa.array(
                [row[f.name] for row in latest.values()], type=f.type
            )
            for f in fields
        },
        schema=schema,
    )
    dest = tmp / "labels" / "labels_public.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dest, compression="zstd")


def _stage_extra(root: Path, tmp: Path) -> None:
    for pattern in EXTRA:
        for f in sorted(root.glob(pattern)):
            if f.is_file():
                rel = f.relative_to(root)
                dest = tmp / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_sha256sums(tmp: Path) -> tuple[int, int]:
    lines = []
    count, total = 0, 0
    for f in sorted(tmp.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(tmp).as_posix()
        if rel in ("SHA256SUMS", "release_manifest.json"):
            continue
        lines.append(f"{_sha256_file(f)}  {rel}\n")
        count += 1
        total += f.stat().st_size
    (tmp / "SHA256SUMS").write_text("".join(lines))
    return count, total


def _git_commit() -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        check=False,
    )
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def stage_release(
    root: Path, release: str, snapshot_id: str, run_ids: list[str]
) -> Path:
    exports = root / "exports"
    final = exports / release
    tmp = exports / f"{release}.tmp"
    if final.exists():
        raise ExportError(f"release {release} already exists")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        _stage_snapshot(root, tmp, snapshot_id)
        _stage_runs(root, tmp, run_ids)
        _stage_samples(root, tmp)
        _stage_labels(root, tmp)
        _stage_extra(root, tmp)
        problems = text_gate(tmp)
        findings = scan_release(tmp)
        if problems or findings:
            detail = problems + [
                f"SECRET {f.rule} {f.path}:{f.line}" for f in findings
            ]
            raise ExportError("release blocked:\n" + "\n".join(detail))
        chunks = chunk_large_files(tmp)
        file_count, total_bytes = _write_sha256sums(tmp)
        manifest = {
            "release": release,
            "snapshot_id": snapshot_id,
            "run_ids": list(run_ids),
            "schema_version": contracts.SCHEMA_VERSION,
            "contains_hn_text": False,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "code_commit": _git_commit(),
            "file_count": file_count,
            "total_bytes": total_bytes,
            "chunks": chunks,
        }
        (tmp / "release_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    tmp.rename(final)
    return final


def chunk_large_files(
    directory: Path, limit: int = 1_900_000_000
) -> dict[str, list[str]]:
    part_re = re.compile(r"\.part\d{3}$")
    chunks = {}
    for f in sorted(directory.rglob("*")):
        if not f.is_file() or part_re.search(f.name):
            continue
        size = f.stat().st_size
        if size <= limit:
            continue
        rel = f.relative_to(directory).as_posix()
        parts = []
        remaining = size
        idx = 0
        with f.open("rb") as src:
            while remaining > 0:
                part_path = f.with_name(f"{f.name}.part{idx:03d}")
                take = min(limit, remaining)
                left = take
                with part_path.open("wb") as dst:
                    while left > 0:
                        block = src.read(min(1 << 20, left))
                        if not block:
                            break
                        dst.write(block)
                        left -= len(block)
                parts.append(part_path.relative_to(directory).as_posix())
                remaining -= take
                idx += 1
        f.unlink()
        chunks[rel] = parts
    return chunks


def verify_release(release_dir: Path) -> dict:
    result = {
        "ok": False,
        "bad": [],
        "missing": [],
        "extra": [],
        "schema_version": None,
    }
    manifest_path = release_dir / "release_manifest.json"
    sums_path = release_dir / "SHA256SUMS"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            result["schema_version"] = manifest.get("schema_version")
        except json.JSONDecodeError:
            pass
    if not manifest_path.exists() or not sums_path.exists():
        return result
    listed = {}
    for line in sums_path.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        if rel:
            listed[rel] = digest
    bad, missing = [], []
    for rel in sorted(listed):
        f = release_dir / rel
        if not f.is_file():
            missing.append(rel)
        elif _sha256_file(f) != listed[rel]:
            bad.append(rel)
    extra = sorted(
        f.relative_to(release_dir).as_posix()
        for f in release_dir.rglob("*")
        if f.is_file()
        and f.relative_to(release_dir).as_posix() not in listed
        and f.relative_to(release_dir).as_posix()
        not in ("SHA256SUMS", "release_manifest.json")
    )
    result["bad"], result["missing"], result["extra"] = bad, missing, extra
    result["ok"] = (
        not bad
        and not missing
        and not extra
        and result["schema_version"] == contracts.SCHEMA_VERSION
    )
    return result

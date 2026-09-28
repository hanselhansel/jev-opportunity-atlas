"""Immutable, checksummed ID shards with resume support.

A shard covers IDs [start, start + size). It is written to a temp file, renamed,
and only then gets a meta file. A shard is *complete* when its meta exists, its
file checksum matches, it has one line per ID, and no ID failed. Complete
shards are never rewritten. A *partial* shard (some IDs failed) is rebuilt by
reusing its successful lines and refetching only the failed IDs.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zstandard as zstd


@dataclass(frozen=True)
class ShardSpec:
    start: int
    size: int

    @property
    def ids(self) -> range:
        return range(self.start, self.start + self.size)

    @property
    def name(self) -> str:
        return f"shard_{self.start:09d}"


def plan_shards(first_id: int, last_id: int, size: int) -> list[ShardSpec]:
    """Shards aligned to multiples of size, covering [first_id, last_id] inclusive."""
    start = (first_id // size) * size
    specs = []
    while start <= last_id:
        specs.append(ShardSpec(start, size))
        start += size
    return specs


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paths(root: Path, spec: ShardSpec) -> tuple[Path, Path]:
    return root / f"{spec.name}.jsonl.zst", root / f"{spec.name}.meta.json"


def read_lines(path: Path) -> list[dict[str, Any]]:
    with open(path, "rb") as f:
        data = zstd.ZstdDecompressor().stream_reader(f).read()
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line]


def shard_status(root: Path, spec: ShardSpec) -> str:
    """missing | corrupt | partial | complete"""
    data_p, meta_p = paths(root, spec)
    if not meta_p.exists() or not data_p.exists():
        return "missing"
    meta = json.loads(meta_p.read_text())
    if meta.get("sha256") != file_sha256(data_p) or meta.get("n_lines") != spec.size:
        return "corrupt"
    return "partial" if meta["states"].get("failed", 0) else "complete"


def reusable_records(root: Path, spec: ShardSpec) -> dict[int, dict[str, Any]]:
    """Non-failed records from a partial shard, keyed by id."""
    if shard_status(root, spec) != "partial":
        return {}
    data_p, _ = paths(root, spec)
    return {r["id"]: r for r in read_lines(data_p) if r["state"] != "failed"}


def write_shard(
    root: Path, spec: ShardSpec, records: list[dict[str, Any]], generation: int
) -> dict:
    ids = [r["id"] for r in records]
    if sorted(ids) != list(spec.ids):
        raise ValueError(f"{spec.name}: records do not cover the shard exactly")
    records = sorted(records, key=lambda r: r["id"])
    root.mkdir(parents=True, exist_ok=True)
    data_p, meta_p = paths(root, spec)
    tmp = data_p.with_suffix(".zst.tmp")
    payload = "".join(
        json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in records
    )
    with open(tmp, "wb") as f:
        f.write(zstd.ZstdCompressor(level=6).compress(payload.encode("utf-8")))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, data_p)
    times = [
        r["item"]["time"] for r in records if r.get("item") and "time" in r["item"]
    ]
    meta = {
        "shard": spec.name,
        "id_start": spec.start,
        "id_end_exclusive": spec.start + spec.size,
        "n_lines": len(records),
        "states": dict(Counter(r["state"] for r in records)),
        "types": dict(
            Counter((r.get("item") or {}).get("type", "none") for r in records)
        ),
        "min_time": min(times) if times else None,
        "max_time": max(times) if times else None,
        "attempts_total": sum(r["attempts"] for r in records),
        "retried_ids": sum(1 for r in records if r["attempts"] > 1),
        "bytes_compressed": data_p.stat().st_size,
        "sha256": file_sha256(data_p),
        "generation": generation,
    }
    meta_tmp = meta_p.with_suffix(".json.tmp")
    meta_tmp.write_text(json.dumps(meta, indent=1))
    os.replace(meta_tmp, meta_p)
    return meta

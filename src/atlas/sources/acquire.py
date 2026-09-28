"""Resumable full-range acquisition from the official HN API.

Usage (via the CLI): locate boundaries once, freeze them in the snapshot
manifest, then fetch every shard. Re-running resumes: complete shards are
skipped, partial shards refetch only failed IDs, missing shards are fetched.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import tomllib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from atlas.sources import shards as sh
from atlas.sources.boundaries import first_id_at_or_after
from atlas.sources.hn_api import fetch_item, make_client, utc_now


def load_config(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def snapshot_dir(root: Path, cfg: dict) -> Path:
    return root / "data" / "raw" / cfg["snapshot_id"]


def log_event(sdir: Path, event: str, **fields) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    with open(sdir / "acquisition_log.jsonl", "a") as f:
        f.write(json.dumps({"at": utc_now(), "event": event, **fields}) + "\n")


async def locate(cfg: dict, sdir: Path) -> dict:
    """Find and freeze the boundary IDs. Never recomputed once frozen."""
    frozen = sdir / "boundaries.json"
    if frozen.exists():
        return json.loads(frozen.read_text())
    async with make_client(8, cfg["request_timeout_s"]) as client:
        maxitem = int((await client.get(f"{cfg['api_base']}/maxitem.json")).text)

        async def fetch(i):
            return await fetch_item(client, cfg["api_base"], i, cfg["max_attempts"])

        first = await first_id_at_or_after(fetch, ts(cfg["window_start"]), 1, maxitem)
        end_first = await first_id_at_or_after(
            fetch, ts(cfg["window_end"]), first, maxitem
        )
    margin = cfg["boundary_margin_ids"]
    b = {
        "window_start": cfg["window_start"],
        "window_end": cfg["window_end"],
        "maxitem_at_locate": maxitem,
        "first_id_in_window": first,
        "last_id_in_window": end_first - 1,
        "scan_first_id": max(1, first - margin),
        "scan_last_id": min(maxitem, end_first - 1 + margin),
        "located_at": utc_now(),
    }
    sdir.mkdir(parents=True, exist_ok=True)
    frozen.write_text(json.dumps(b, indent=1))
    log_event(sdir, "boundaries_frozen", **b)
    return b


def disk_guard(
    sdir: Path, n_ids: int, bytes_per_id: float, headroom_gib: float
) -> None:
    free = shutil.disk_usage(sdir if sdir.exists() else sdir.parent.parent).free
    need = n_ids * bytes_per_id + headroom_gib * 2**30
    if need > free:
        raise SystemExit(
            f"Disk guard: need ~{need / 2**30:.1f} GiB (incl. {headroom_gib} GiB headroom), "
            f"free {free / 2**30:.1f} GiB. Free space or lower scope."
        )


async def fetch_shard(client, sem, cfg, sdir, spec) -> dict | None:
    status = sh.shard_status(sdir / "shards", spec)
    if status == "complete":
        return None
    keep = sh.reusable_records(sdir / "shards", spec)
    todo = [i for i in spec.ids if i not in keep]

    async def one(i):
        async with sem:
            return await fetch_item(client, cfg["api_base"], i, cfg["max_attempts"])

    t0 = time.monotonic()
    fresh = await asyncio.gather(*(one(i) for i in todo))
    records = list(keep.values()) + [asdict(r) for r in fresh]
    prev = sdir / "shards" / f"{spec.name}.meta.json"
    gen = json.loads(prev.read_text()).get("generation", 0) + 1 if prev.exists() else 1
    meta = sh.write_shard(sdir / "shards", spec, records, gen)
    log_event(
        sdir,
        "shard_written",
        shard=spec.name,
        prior_status=status,
        fetched=len(todo),
        reused=len(keep),
        wall_s=round(time.monotonic() - t0, 2),
        states=meta["states"],
    )
    return meta


async def run(
    cfg: dict,
    root: Path,
    limit_shards: int | None = None,
    worker: tuple[int, int] = (0, 1),
) -> dict:
    """Fetch this worker's shards. Workers split shards by index mod n_workers,
    so parallel processes never write the same shard file."""
    idx, n_workers = worker
    sdir = snapshot_dir(root, cfg)
    b = await locate(cfg, sdir)
    specs = sh.plan_shards(b["scan_first_id"], b["scan_last_id"], cfg["shard_size"])
    if limit_shards:
        specs = specs[:limit_shards]
    specs = [s for k, s in enumerate(specs) if k % n_workers == idx]
    todo = [s for s in specs if sh.shard_status(sdir / "shards", s) != "complete"]
    done_bytes = (
        [
            json.loads(p.read_text())["bytes_compressed"]
            / json.loads(p.read_text())["n_lines"]
            for p in (sdir / "shards").glob("*.meta.json")
        ]
        if (sdir / "shards").exists()
        else []
    )
    per_id = max(done_bytes) if done_bytes else 400.0
    disk_guard(
        sdir, len(todo) * cfg["shard_size"], per_id * 1.2, cfg["disk_headroom_gib"]
    )
    log_event(
        sdir, "run_start", worker=idx, n_workers=n_workers,
        shards_total=len(specs), shards_todo=len(todo),
    )
    t0 = time.monotonic()
    sem = asyncio.Semaphore(cfg["concurrency"])
    shard_sem = asyncio.Semaphore(cfg["concurrent_shards"])
    async with make_client(cfg["concurrency"], cfg["request_timeout_s"]) as client:

        async def guarded(spec):
            async with shard_sem:
                meta = await fetch_shard(client, sem, cfg, sdir, spec)
                if meta:
                    print(f"{utc_now()} {spec.name} {meta['states']}", flush=True)
                return meta

        metas = await asyncio.gather(*(guarded(s) for s in todo))
    summary = {
        "worker": idx,
        "shards_total": len(specs),
        "shards_fetched": len(todo),
        "wall_s": round(time.monotonic() - t0, 1),
        "partial_after_run": sum(1 for m in metas if m and m["states"].get("failed")),
    }
    log_event(sdir, "run_end", **summary)
    return summary

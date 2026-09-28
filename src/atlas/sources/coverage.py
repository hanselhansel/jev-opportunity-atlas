"""Coverage report over shard metadata: every scanned ID has exactly one state."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from atlas.sources import shards as sh
from atlas.sources.acquire import snapshot_dir


def report(cfg: dict, root: Path) -> dict:
    sdir = snapshot_dir(root, cfg)
    b = json.loads((sdir / "boundaries.json").read_text())
    specs = sh.plan_shards(b["scan_first_id"], b["scan_last_id"], cfg["shard_size"])
    status = Counter()
    states = Counter()
    types = Counter()
    nbytes = 0
    for spec in specs:
        st = sh.shard_status(sdir / "shards", spec)
        status[st] += 1
        if st in ("complete", "partial"):
            meta = json.loads(sh.paths(sdir / "shards", spec)[1].read_text())
            states.update(meta["states"])
            types.update(meta["types"])
            nbytes += meta["bytes_compressed"]
    ids_scanned = sum(states.values())
    return {
        "snapshot_id": cfg["snapshot_id"],
        "boundaries": b,
        "shards": dict(status),
        "shards_total": len(specs),
        "ids_scanned": ids_scanned,
        "id_states": dict(states),
        "item_types": dict(types),
        "compressed_gib": round(nbytes / 2**30, 3),
        "note": "Window filter by item time is applied at snapshot build, not here.",
    }

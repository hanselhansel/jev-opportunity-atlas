"""Packed-screen answers for the calibration comments that lack them (L22).

Reads the calibration queue (`data/labels/queues/calibration.json`), drops
ids the packed experiment already covers (`runs/<pilot>-packed/
packed_map.parquet`), packs the rest k-at-a-time, and dispatches under the
pilot budget as run ``<pilot>-packedcal`` so packed and single answers can
both be scored against the blind labels on the same comments.

Ported from the main run's packed_calibration script; the packed map keeps
the long format `packed_id, slot, comment_id` (`packed.PACKED_MAP`).

See docs/runbook-main-run.md.
"""

from __future__ import annotations

import json

import pyarrow.parquet as pq

from atlas import paths
from atlas.pilot import stages
from atlas.pilot.packed import PACKED_LABEL, packed_items, packed_question_set
from atlas.sources.items import load_items

K = 5


def run_packed_cal(run_id, k: int = K, budget: str = "pilot", yes=False) -> dict:
    """Packed screen over calibration ids missing from `<run_id>-packed`."""
    queue = json.loads(
        (paths.LABELS / "queues" / "calibration.json").read_text(
            encoding="utf-8"
        )
    )
    cal_ids = sorted({int(i) for i in queue["ids"]})
    map_path = paths.run_dir(f"{run_id}-packed") / "packed_map.parquet"
    already = (
        {int(x) for x in pq.read_table(map_path).column("comment_id")}
        if map_path.exists()
        else set()
    )
    todo = [i for i in cal_ids if i not in already]
    print(
        f"calibration ids {len(cal_ids)}, already packed "
        f"{len(cal_ids) - len(todo)}, to pack {len(todo)}",
        flush=True,
    )
    pilot = stages.read_pilot_json(run_id)
    items = load_items(paths.snapshot_dir(pilot["snapshot_id"]), todo)
    packed_list, packed_map = packed_items(items, k=k)
    qs = packed_question_set(k)
    est = stages.estimate(packed_list, qs, budget)
    stages.print_estimate(est)
    out = {
        "estimate": est,
        "calibration_ids": len(cal_ids),
        "already_packed": len(cal_ids) - len(todo),
        "todo": len(todo),
        "run_id": f"{run_id}-packedcal",
        "question_set": PACKED_LABEL,
    }
    if not yes:
        return {**out, "dispatched": False}
    run_dir = paths.run_dir(out["run_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(packed_map, run_dir / "packed_map.parquet")
    return {
        **out,
        "dispatched": True,
        "run": stages.dispatch(out["run_id"], packed_list, qs, budget),
    }

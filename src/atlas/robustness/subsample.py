"""Subsamples for the paraphrase-robustness runs.

``subsample_screen`` draws a stratified SRSWOR within the parent sample's
``stratum``, allocated proportionally to stratum size (Hamilton), and rescales
each weight by (parent rows in stratum) / (subsample rows in stratum) so the
weights still sum to the population the parent represents. ``subsample_items``
draws a seeded SRSWOR of an items parquet, sorted by ``comment_id``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.sampling.select import allocate, write_manifest


def subsample_rows(parent: pa.Table, n: int, seed: int) -> pa.Table:
    """Stratified SRSWOR of `parent` (a contract SAMPLE table), weights rescaled
    by parent/stratum size over subsample/stratum size."""
    labels = parent.column("stratum").to_numpy(zero_copy_only=False).astype(str)
    ids = parent.column("comment_id").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(labels, return_counts=True)
    sizes = {str(u): int(c) for u, c in zip(uniq, counts)}
    alloc = allocate(sizes, min(n, parent.num_rows), min_per_stratum=1)
    rng = np.random.Generator(np.random.PCG64(seed))
    keep = np.zeros(parent.num_rows, dtype=bool)
    for label in sorted(sizes):
        idx = np.flatnonzero(labels == label)
        idx = idx[np.argsort(ids[idx], kind="stable")]  # ascending comment_id
        n_h = alloc[label]
        keep[idx[rng.choice(idx.size, n_h, replace=False)]] = True
    sub = parent.filter(keep).to_pylist()
    parent_n = {str(u): int(c) for u, c in zip(uniq, counts)}
    sub_n = {g: 0 for g in sizes}
    for r in sub:
        sub_n[r["stratum"]] += 1
    rows = []
    for i, r in enumerate(sorted(sub, key=lambda r: r["draw_order"])):
        weight = r["weight"] * parent_n[r["stratum"]] / sub_n[r["stratum"]]
        rows.append(
            {
                "sample_id": r["sample_id"],
                "comment_id": r["comment_id"],
                "story_id": r["story_id"],
                "stratum": r["stratum"],
                "inclusion_prob": 1.0 / weight,
                "weight": weight,
                "batch": 1,
                "draw_order": i,
            }
        )
    return pa.Table.from_pylist(rows, schema=contracts.SAMPLE)


def subsample_screen(
    sample_id: str, n: int, seed: int, out_id: str
) -> pa.Table:
    """Subsample `sample_id`, write <out_id>.parquet plus the JSON sidecar."""
    if paths.sample_path(out_id).exists():
        raise SystemExit(f"{out_id} already exists; refusing to overwrite")
    parent = pq.read_table(paths.sample_path(sample_id))
    meta = json.loads(
        (paths.SAMPLES / f"{sample_id}.json").read_text(encoding="utf-8")
    )
    table = subsample_rows(parent, n, seed)
    table = table.set_column(
        table.schema.get_field_index("sample_id"),
        "sample_id",
        pa.repeat(out_id, table.num_rows),
    )
    out_meta = {
        "seed": seed,
        "seeds_by_batch": {"1": seed},
        "frame_snapshot_id": meta["frame_snapshot_id"],
        "design_version": "subsample",
        "parent_sample_id": sample_id,
    }
    manifest = write_manifest(table, out_meta, paths.SAMPLES)
    dest = paths.MANIFESTS / "samples"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(paths.SAMPLES / f"{out_id}.json", dest / f"{out_id}.json")
    assert manifest["sample_id"] == out_id
    return table


def subsample_items(
    items_path, n: int, seed: int, out
) -> pa.Table:
    """Seeded SRSWOR of an items parquet, sorted by comment_id, written to `out`."""
    table = pq.read_table(Path(items_path))
    k = min(int(n), table.num_rows)
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(table.num_rows, k, replace=False))
    sub = table.take(pa.array(idx))
    order = np.argsort(
        sub.column("comment_id").to_numpy(zero_copy_only=False), kind="stable"
    )
    sub = sub.take(pa.array(order))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(sub, out)
    return sub

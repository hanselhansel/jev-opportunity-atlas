"""Pilot draw: one stratified SRSWOR over the v2 design frame.

Each stratum gets `min(N_h, max(min_per_stratum, round(n_target*N_h/N)))` —
proportional to size with a floor — so every stratum has enough pilot answers
to estimate its firsthand rate. The draw is idempotent: an existing sample is
reused only when the sidecar's parameters and parquet sha256 match exactly;
any other existing file raises instead of overwriting.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.sampling import design_v2, select

RULE = "min(N_h, max(min_per_stratum, round(n_target*N_h/N)))"


def pilot_draw(
    snapshot_id: str,
    n_target: int = 2000,
    min_per_stratum: int = 20,
    seed: int = 20260929,
) -> pa.Table:
    """Draw (or reload) pilot sample `pilot-<seed>`; never redraws or overwrites."""
    sample_id = f"pilot-{seed}"
    out = paths.sample_path(sample_id)
    if out.exists():
        sidecar = out.with_suffix(".json")
        if not sidecar.exists():
            raise ValueError(f"{out} exists without a sidecar; refusing to reuse")
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        same = (
            meta.get("sha256") == hashlib.sha256(out.read_bytes()).hexdigest()
            and meta.get("seed") == seed
            and meta.get("n_target") == n_target
            and meta.get("min_per_stratum") == min_per_stratum
            and meta.get("frame_snapshot_id") == snapshot_id
        )
        if not same:
            raise ValueError(f"{out} exists with different draw parameters")
        return pq.read_table(out)

    sdir = paths.snapshot_dir(snapshot_id)
    comments = pq.read_table(
        sdir / "comments.parquet",
        columns=[
            "id",
            "story_id",
            "period",
            "thread_type",
            "text_norm",
            "word_count",
            "eligible",
        ],
    )
    stories = pq.read_table(sdir / "stories.parquet", columns=["id", "thread_type"])
    frame = design_v2.build_frame_v2(comments, stories)
    sizes = select._sizes(frame)
    n = frame.num_rows
    alloc = {
        h: min(n_h, max(min_per_stratum, round(n_target * n_h / n)))
        for h, n_h in sizes.items()
    }
    table = design_v2.draw_allocated(frame, alloc, seed, sample_id)
    meta = {
        "seed": seed,
        "seeds_by_batch": {"1": seed},
        "frame_snapshot_id": snapshot_id,
        "design_version": "v2",
        "purpose": "pilot",
        "n_target": n_target,
        "min_per_stratum": min_per_stratum,
    }
    design = {
        "pain_patterns_version": design_v2.PAIN_PATTERNS_VERSION,
        "rule": RULE,
        "allocation": alloc,
        "N_h": sizes,
    }
    design_v2.write_design_manifest(table, meta, design, paths.SAMPLES)
    dest = paths.MANIFESTS / "samples"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(paths.SAMPLES / f"{sample_id}.json", dest / f"{sample_id}.json")
    return table

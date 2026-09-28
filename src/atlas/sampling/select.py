"""Stratified selection: Hamilton allocation, SRSWOR draws, expansions, manifests."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas import contracts

ALGORITHM = "stratified SRSWOR, Hamilton proportional allocation, PCG64"


class SamplingError(ValueError):
    """Raised when a sample cannot satisfy the design's coverage invariants."""


def _hamilton(sizes: dict[str, int], n: int) -> dict[str, int]:
    """Floor of n*N_h/sum(N), then +1 each by largest remainder, ties by label."""
    labels = sorted(sizes)
    total = sum(sizes[h] for h in labels)
    if total <= 0:
        return {h: 0 for h in labels}
    exact = {h: n * sizes[h] / total for h in labels}
    alloc = {h: math.floor(exact[h]) for h in labels}
    leftover = n - sum(alloc.values())
    order = sorted(labels, key=lambda h: (-(exact[h] - alloc[h]), h))
    for h in order[:leftover]:
        alloc[h] += 1
    return alloc


def allocate(
    sizes: dict[str, int], n: int, min_per_stratum: int = 0
) -> dict[str, int]:
    """Hamilton proportional allocation with per-stratum floors and size caps."""
    total = sum(sizes.values())
    if n < 0 or n > total:
        raise ValueError(f"n={n} outside [0, {total}]")
    floors = {h: min(s, min_per_stratum) for h, s in sizes.items()}
    if sum(floors.values()) > n:
        raise ValueError(f"min_per_stratum infeasible: floors {sum(floors.values())} > n={n}")
    fixed: dict[str, int] = {}
    while True:
        free = sorted(h for h in sizes if h not in fixed)
        r = n - sum(fixed.values())
        alloc = _hamilton({h: sizes[h] for h in free}, r)
        changed = False
        for h in free:
            if alloc[h] < floors[h]:
                fixed[h] = floors[h]
                changed = True
            elif alloc[h] > sizes[h]:
                fixed[h] = sizes[h]
                changed = True
        if not changed:
            out = {**fixed, **alloc}
            assert sum(out.values()) == n
            return {h: out[h] for h in sorted(out)}


def collapse(frame: pa.Table, level: int) -> pa.Table:
    """Level 0 identity; 1 drops the tier; 2 drops tier and thread_type."""
    if level == 0:
        return frame
    keep = 2 if level == 1 else 1
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    uniq, inv = np.unique(labels, return_inverse=True)
    collapsed = np.array(["|".join(u.split("|")[:keep]) for u in uniq])
    return frame.set_column(
        frame.schema.get_field_index("stratum"),
        "stratum",
        pa.array(collapsed[inv], type=pa.string()),
    )


def _sizes(frame: pa.Table) -> dict[str, int]:
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(labels, return_counts=True)
    return {str(u): int(c) for u, c in zip(uniq, counts)}


def resolve_strata(
    frame: pa.Table, n: int, min_per_stratum: int
) -> tuple[pa.Table, int]:
    """First collapse level whose floors fit n; SamplingError if none does."""
    for level in (0, 1, 2):
        f = collapse(frame, level)
        if sum(min(s, min_per_stratum) for s in _sizes(f).values()) <= n:
            return f, level
    raise SamplingError(f"n={n} cannot cover strata even at collapse level 2")


def _draw_rows(
    frame: pa.Table, alloc: dict[str, int], rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """Draw alloc[h] ids per stratum in sorted label order from ids ascending."""
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    ids = frame.column("comment_id").to_numpy(zero_copy_only=False)
    uniq, inv = np.unique(labels, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
    picked = np.empty(0, dtype=np.int64)
    stratum_col = np.empty(0, dtype=object)
    for k, label in enumerate(uniq):
        group = ids[order[bounds[k] : bounds[k + 1]]]  # ascending comment_id
        n_h = alloc[str(label)]
        chosen = group[rng.choice(group.size, n_h, replace=False)]
        picked = np.concatenate([picked, chosen])
        stratum_col = np.concatenate([stratum_col, np.full(n_h, label, dtype=object)])
    return {"comment_id": picked, "stratum": stratum_col}


def _story_ids(frame: pa.Table, comment_ids: np.ndarray) -> pa.Array:
    idx = pc.index_in(pa.array(comment_ids), value_set=frame.column("comment_id"))
    return pc.take(frame.column("story_id"), idx)


def _check(table: pa.Table, frame_rows: int) -> None:
    weights = table.column("weight").to_numpy(zero_copy_only=False)
    if not math.isclose(
        float(weights.sum()), float(frame_rows), rel_tol=1e-12, abs_tol=1e-6
    ):
        raise SamplingError(f"sum(weight)={weights.sum()} != frame rows {frame_rows}")
    labels = table.column("stratum").to_numpy(zero_copy_only=False)
    _, counts = np.unique(labels, return_counts=True)
    if counts.size == 0 or int(counts.min()) < 1:
        raise SamplingError("a nonempty stratum received n_h = 0")


def _finish(
    frame: pa.Table,
    comment_ids: np.ndarray,
    strata: np.ndarray,
    sample_id: str,
    batch: np.ndarray,
    draw_order: np.ndarray,
) -> pa.Table:
    sizes = _sizes(frame)
    n_map = {str(u): int(c) for u, c in zip(*np.unique(strata, return_counts=True))}
    prob = np.array([n_map[str(s)] / sizes[str(s)] for s in strata])
    weight = np.array([sizes[str(s)] / n_map[str(s)] for s in strata])
    table = pa.table(
        {
            "sample_id": pa.repeat(sample_id, len(comment_ids)),
            "comment_id": pa.array(comment_ids, type=pa.int64()),
            "story_id": _story_ids(frame, comment_ids),
            "stratum": pa.array(strata, type=pa.string()),
            "inclusion_prob": pa.array(prob, type=pa.float64()),
            "weight": pa.array(weight, type=pa.float64()),
            "batch": pa.array(batch, type=pa.int32()),
            "draw_order": pa.array(draw_order, type=pa.int64()),
        },
        schema=contracts.SAMPLE,
    )
    return table


def draw(
    frame: pa.Table, n: int, seed: int, sample_id: str, min_per_stratum: int = 2
) -> pa.Table:
    """Stratified SRSWOR sample of n comments, contract SAMPLE, batch 1."""
    if n > frame.num_rows:
        raise ValueError(f"n={n} exceeds frame rows {frame.num_rows}")
    resolved, _level = resolve_strata(frame, n, min_per_stratum)
    alloc = allocate(_sizes(resolved), n, min_per_stratum)
    rng = np.random.Generator(np.random.PCG64(seed))
    got = _draw_rows(resolved, alloc, rng)
    n_rows = len(got["comment_id"])
    table = _finish(
        resolved,
        got["comment_id"],
        got["stratum"],
        sample_id,
        np.ones(n_rows, dtype=np.int32),
        np.arange(n_rows, dtype=np.int64),
    )
    _check(table, resolved.num_rows)
    return table


def expand(
    frame: pa.Table,
    previous: pa.Table,
    extra: int,
    seed: int,
    min_per_stratum: int = 0,
    sample_id: str | None = None,
) -> pa.Table:
    """Add `extra` units as a new batch; recompute probabilities for all rows.

    The extra size and its allocation may depend only on stratum counts, never on
    observed answers, or the recomputed probabilities are wrong. Each batch is an
    SRS from the not-yet-selected units, so the combined sample is a stratified
    SRSWOR of the combined size. `frame` must already sit at the collapse level
    used for `previous`.
    """
    prev_ids = previous.column("comment_id")
    mask = pc.invert(pc.is_in(frame.column("comment_id"), value_set=prev_ids))
    remaining = frame.filter(mask)
    alloc = allocate(_sizes(remaining), extra, min_per_stratum)
    rng = np.random.Generator(np.random.PCG64(seed))
    got = _draw_rows(remaining, alloc, rng)
    prev_order = previous.column("draw_order").to_numpy(zero_copy_only=False)
    prev_batch = previous.column("batch").to_numpy(zero_copy_only=False)
    batch = int(prev_batch.max()) + 1 if prev_batch.size else 1
    start = int(prev_order.max()) + 1 if prev_order.size else 0
    n_new = len(got["comment_id"])
    sid = sample_id or previous.column("sample_id")[0].as_py()
    new_table = _finish(
        frame,
        got["comment_id"],
        got["stratum"],
        sid,
        np.full(n_new, batch, dtype=np.int32),
        np.arange(start, start + n_new, dtype=np.int64),
    )
    combined = pa.concat_tables([previous, new_table])
    combined = combined.set_column(
        combined.schema.get_field_index("sample_id"),
        "sample_id",
        pa.repeat(sid, combined.num_rows),
    )
    labels = combined.column("stratum").to_numpy(zero_copy_only=False)
    sizes = _sizes(frame)
    n_map = {str(u): int(c) for u, c in zip(*np.unique(labels, return_counts=True))}
    prob = np.array([n_map[str(s)] / sizes[str(s)] for s in labels])
    weight = np.array([sizes[str(s)] / n_map[str(s)] for s in labels])
    combined = combined.set_column(
        combined.schema.get_field_index("inclusion_prob"),
        "inclusion_prob",
        pa.array(prob, type=pa.float64()),
    )
    combined = combined.set_column(
        combined.schema.get_field_index("weight"),
        "weight",
        pa.array(weight, type=pa.float64()),
    )
    _check(combined, frame.num_rows)
    return combined


def write_manifest(table: pa.Table, meta: dict, out_dir) -> dict:
    """Write <sample_id>.parquet plus a JSON sidecar; return the manifest dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = table.to_pylist()
    sample_id = rows[0]["sample_id"] if rows else meta["sample_id"]
    parquet_path = out_dir / f"{sample_id}.parquet"
    pq.write_table(table, parquet_path)
    sha = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    strata: dict[str, dict[str, int]] = {}
    for r in rows:
        e = strata.setdefault(r["stratum"], {"N_h": 0, "n_h": 0})
        e["n_h"] += 1
        e["N_h"] = round(e["n_h"] * r["weight"])
    manifest = {
        **meta,
        "sample_id": sample_id,
        "n": len(rows),
        "algorithm": ALGORITHM,
        "strata": strata,
        "sha256": sha,
    }
    (out_dir / f"{sample_id}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def draw_from_snapshot(
    snapshot_id: str,
    n: int,
    seed: int,
    sample_id: str,
    min_per_stratum: int = 2,
) -> pa.Table:
    """Draw (or reload) the sample for a snapshot; never redraws or overwrites."""
    from atlas import paths
    from atlas.sampling.frame import build_frame, engagement_cutpoints

    out = paths.sample_path(sample_id)
    if out.exists():
        sidecar = out.with_suffix(".json")
        if not sidecar.exists():
            raise SamplingError(f"{out} exists without a sidecar; refusing to reuse")
        meta = json.loads(sidecar.read_text())
        same = (
            meta.get("sha256") == _sha256(out)
            and meta.get("seed") == seed
            and meta.get("n") == n
            and meta.get("frame_snapshot_id") == snapshot_id
        )
        if not same:
            raise SamplingError(f"{out} exists with different draw parameters")
        return pq.read_table(out)

    sdir = paths.snapshot_dir(snapshot_id)
    comments = pq.read_table(
        sdir / "comments.parquet",
        columns=["id", "story_id", "period", "thread_type", "eligible"],
    )
    stories = pq.read_table(sdir / "stories.parquet", columns=["id", "descendants"])
    eligible = comments.filter(pc.equal(comments.column("eligible"), True))
    story_ids = pa.array(
        sorted(set(eligible.column("story_id").to_pylist()) - {None})
    )
    eligible_stories = stories.filter(
        pc.is_in(stories.column("id"), value_set=story_ids)
    )
    descendants = [
        d
        for d in eligible_stories.column("descendants").to_pylist()
        if d is not None
    ]
    if not descendants:
        raise SamplingError(f"no eligible comments in snapshot {snapshot_id}")
    cutpoints = engagement_cutpoints(descendants)
    frame = build_frame(comments, stories, cutpoints)
    resolved, level = resolve_strata(frame, n, min_per_stratum)
    table = draw(resolved, n, seed, sample_id, min_per_stratum)
    meta = {
        "seed": seed,
        "seeds_by_batch": {"1": seed},
        "cutpoints": list(cutpoints),
        "frame_snapshot_id": snapshot_id,
        "collapse_level": level,
        "min_per_stratum": min_per_stratum,
    }
    manifest = write_manifest(table, meta, paths.SAMPLES)
    dest = paths.MANIFESTS / "samples"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(paths.SAMPLES / f"{sample_id}.json", dest / f"{sample_id}.json")
    assert manifest["sample_id"] == sample_id
    return table

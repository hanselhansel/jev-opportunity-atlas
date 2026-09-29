"""S6: the Show HN launch sample.

Population: `stories.parquet` rows with `in_window` true and a title starting
with "Show HN" (case-insensitive). Strata are the window periods P01..P12;
each month contributes round(n * N_h / N) stories drawn SRSWOR, so every
launch carries weight N_h / n_h and the weights sum to the population size.

The draw is idempotent: `builders-<seed>.parquet` plus a JSON sidecar are
written once under `data/samples/`; a rerun with the same snapshot, n, and
seed reloads, and a rerun with different parameters refuses.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.sampling.select import SamplingError

DEFAULT_N = 8000
DEFAULT_SEED = 20261006
SHOW_HN = re.compile(r"^\s*show\s*hn\b", re.IGNORECASE)

SAMPLE_SCHEMA = pa.schema(
    [
        ("story_id", pa.int64()),
        ("period", pa.string()),
        ("weight", pa.float64()),
    ]
)


def sample_id_for(seed: int) -> str:
    return f"builders-{seed}"


def is_show_hn(title: str | None) -> bool:
    return bool(SHOW_HN.match(title or ""))


def _window(snapshot_id: str) -> tuple[int, int]:
    """(window_start, window_end) as epoch seconds: the snapshot manifest wins,
    falling back to configs/acquisition.toml."""
    from atlas.sources.acquire import ts

    manifest = paths.snapshot_dir(snapshot_id) / "manifest.json"
    if manifest.exists():
        w = json.loads(manifest.read_text(encoding="utf-8"))["window"]
        return ts(w["start"]), ts(w["end"])
    cfg = tomllib.loads(
        (paths.CONFIGS / "acquisition.toml").read_text(encoding="utf-8")
    )
    return ts(cfg["window_start"]), ts(cfg["window_end"])


def launch_frame(snapshot_id: str) -> pa.Table:
    """story_id, period rows for every in-window Show HN launch."""
    sdir = paths.snapshot_dir(snapshot_id)
    stories = pq.read_table(
        sdir / "stories.parquet",
        columns=["id", "time", "title", "in_window"],
    )
    ws, we = _window(snapshot_id)
    ids: list[int] = []
    periods: list[str] = []
    for r in stories.to_pylist():
        if not r["in_window"] or not is_show_hn(r["title"]):
            continue
        period = contracts.period_of(int(r["time"]), ws, we)
        if period is None:
            continue
        ids.append(int(r["id"]))
        periods.append(period)
    order = np.argsort(np.asarray(ids, dtype=np.int64), kind="stable")
    return pa.table(
        {
            "story_id": pa.array(
                np.asarray(ids, dtype=np.int64)[order], type=pa.int64()
            ),
            "period": pa.array(
                np.asarray(periods, dtype=object)[order], type=pa.string()
            ),
        }
    )


def month_allocation(sizes: dict[str, int], n: int) -> dict[str, int]:
    """n_h = round(n * N_h / N), clipped to [0, N_h]."""
    total = sum(sizes.values())
    return {
        h: min(sizes[h], max(0, round(n * sizes[h] / total)))
        for h in sizes
    }


def _draw(frame: pa.Table, n: int, seed: int) -> pa.Table:
    ids = frame.column("story_id").to_numpy(zero_copy_only=False)
    periods = frame.column("period").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(periods, return_counts=True)
    sizes = {str(u): int(c) for u, c in zip(uniq, counts)}
    if n > frame.num_rows:
        raise ValueError(
            f"n={n} exceeds the {frame.num_rows} in-window Show HN launches"
        )
    alloc = month_allocation(sizes, n)
    rng = np.random.Generator(np.random.PCG64(seed))
    out_id: list[int] = []
    out_period: list[str] = []
    out_weight: list[float] = []
    for h in sorted(sizes):
        n_h = alloc[h]
        if n_h <= 0:
            continue
        idx = np.nonzero(periods == h)[0]
        chosen = rng.choice(idx.size, n_h, replace=False)
        picked = np.sort(ids[idx[chosen]])
        out_id.extend(int(i) for i in picked)
        out_period.extend([h] * n_h)
        out_weight.extend([sizes[h] / n_h] * n_h)
    if not out_id:
        raise SamplingError(f"n={n} draws nothing from {frame.num_rows} launches")
    return pa.table(
        {
            "story_id": pa.array(out_id, type=pa.int64()),
            "period": pa.array(out_period, type=pa.string()),
            "weight": pa.array(out_weight, type=pa.float64()),
        },
        schema=SAMPLE_SCHEMA,
    )


def _write_manifest(
    table: pa.Table, frame: pa.Table, snapshot_id: str, n: int, seed: int
) -> dict:
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    sample_id = sample_id_for(seed)
    out = paths.sample_path(sample_id)
    pq.write_table(table, out)
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    f_uniq, f_counts = np.unique(
        frame.column("period").to_numpy(zero_copy_only=False),
        return_counts=True,
    )
    f_sizes = {str(u): int(c) for u, c in zip(f_uniq, f_counts)}
    s_uniq, s_counts = np.unique(
        table.column("period").to_numpy(zero_copy_only=False),
        return_counts=True,
    )
    s_sizes = {str(u): int(c) for u, c in zip(s_uniq, s_counts)}
    strata = {
        h: {"N_h": f_sizes[h], "n_h": s_sizes.get(h, 0)} for h in f_sizes
    }
    manifest = {
        "sample_id": sample_id,
        "kind": "builders",
        "frame_snapshot_id": snapshot_id,
        "seed": seed,
        "n": n,
        "n_drawn": table.num_rows,
        "population": int(sum(f_sizes.values())),
        "algorithm": "month-stratified SRSWOR, proportional round allocation",
        "strata": strata,
        "sha256": sha,
    }
    (paths.SAMPLES / f"{sample_id}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    dest = paths.MANIFESTS / "samples"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(paths.SAMPLES / f"{sample_id}.json", dest / f"{sample_id}.json")
    return manifest


def _reuse_ok(out: Path, meta: dict, snapshot_id: str, n: int, seed: int) -> bool:
    return (
        meta.get("sha256") == hashlib.sha256(out.read_bytes()).hexdigest()
        and meta.get("seed") == seed
        and meta.get("n") == n
        and meta.get("frame_snapshot_id") == snapshot_id
    )


def draw_launches(
    snapshot_id: str, n: int = DEFAULT_N, seed: int = DEFAULT_SEED
) -> pa.Table:
    """Draw (or reload) the launch sample; never redraws or overwrites."""
    out = paths.sample_path(sample_id_for(seed))
    sidecar = out.with_suffix(".json")
    if out.exists():
        if not sidecar.exists():
            raise SamplingError(
                f"{out} exists without a sidecar; refusing to reuse"
            )
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        if not _reuse_ok(out, meta, snapshot_id, n, seed):
            raise SamplingError(
                f"{out} exists with different draw parameters"
            )
        return pq.read_table(out)
    frame = launch_frame(snapshot_id)
    table = _draw(frame, n, seed)
    _write_manifest(table, frame, snapshot_id, n, seed)
    return table

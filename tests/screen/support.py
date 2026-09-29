"""Shared helpers for screen lane tests: a synthetic 1000-comment sample over
the pilotsnap snapshot, plus an integer-nanosecond fake clock for the runner's
rate limiter.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.inference import ratelimit
from tests.pilot.test_support import SNAPSHOT_ID

SAMPLE_N = 1000


def mock_runtime(monkeypatch, seen=None):
    """Mock Jev transport plus a fake limiter clock so rpm pacing is instant."""
    from tests.pilot.test_support import make_transport, mock_env

    mock_env(monkeypatch, make_transport(seen=seen))
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)
    return clock


class FakeClock:
    """Integer-nanosecond clock; bucket sleeps land exactly on lattice points."""

    def __init__(self):
        self.ns = 0

    def now(self):
        return self.ns / 1e9

    async def sleep(self, delay):
        self.ns += round(delay * 1e9)
        await asyncio.sleep(0)


def write_sample(sample_id="screen-s1", n=SAMPLE_N, seed=11):
    """Sample `n` eligible comments, stored SHUFFLED so tests prove sorting.

    Returns (sample_id, sorted comment ids).
    """
    from atlas.sampling.design_v2 import build_frame_v2

    sdir = paths.snapshot_dir(SNAPSHOT_ID)
    comments = pq.read_table(sdir / "comments.parquet")
    stories = pq.read_table(sdir / "stories.parquet")
    frame = build_frame_v2(comments, stories)
    by_id = {r["comment_id"]: r for r in frame.to_pylist()}
    eligible = sorted(by_id)
    rng = np.random.default_rng(seed)
    chosen = [int(c) for c in rng.choice(eligible, size=n, replace=False)]
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    prob = n / len(eligible)
    rows = []
    for draw_order, pos in enumerate(rng.permutation(n)):
        cid = chosen[int(pos)]
        rows.append(
            {
                "sample_id": sample_id,
                "comment_id": cid,
                "story_id": int(by_id[cid]["story_id"]),
                "stratum": by_id[cid]["stratum"],
                "inclusion_prob": prob,
                "weight": 1 / prob,
                "batch": 1,
                "draw_order": draw_order,
            }
        )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.SAMPLE),
        paths.sample_path(sample_id),
    )
    sidecar = {
        "frame_snapshot_id": SNAPSHOT_ID,
        "design_version": "v2",
        "n": n,
    }
    (paths.SAMPLES / f"{sample_id}.json").write_text(
        json.dumps(sidecar, indent=1) + "\n", encoding="utf-8"
    )
    return sample_id, sorted(chosen)

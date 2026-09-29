"""Task 25.2: `robust subsample-screen` and `robust subsample-items`.

The screen subsample is a stratified SRSWOR within the parent sample's
`stratum`, proportional to stratum size, with weights rescaled so they still
sum to the parent total. The item subsample is a seeded SRSWOR sorted by
comment_id.
"""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.robustness.subsample import (
    subsample_items,
    subsample_rows,
    subsample_screen,
)

STRATA = {"a": (60, 10.0), "b": (30, 20.0), "c": (10, 5.0)}
PARENT_TOTAL = 60 * 10.0 + 30 * 20.0 + 10 * 5.0  # 1250


def _parent_table(sample_id="parent"):
    rows = []
    cid = 9_000_000_000
    for name, (count, weight) in STRATA.items():
        for _ in range(count):
            rows.append(
                {
                    "sample_id": sample_id,
                    "comment_id": cid,
                    "story_id": 9_000_100_000 + cid % 7,
                    "stratum": name,
                    "inclusion_prob": 1.0 / weight,
                    "weight": weight,
                    "batch": 1,
                    "draw_order": cid - 9_000_000_000,
                }
            )
            cid += 1
    return pa.Table.from_pylist(rows, schema=contracts.SAMPLE)


def _write_parent(tmp_path, monkeypatch, sample_id="parent"):
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    monkeypatch.setattr(paths, "MANIFESTS", tmp_path / "manifests")
    paths.SAMPLES.mkdir(parents=True)
    pq.write_table(_parent_table(sample_id), paths.sample_path(sample_id))
    (paths.SAMPLES / f"{sample_id}.json").write_text(
        json.dumps(
            {"sample_id": sample_id, "frame_snapshot_id": "snap-x", "n": 100}
        )
        + "\n"
    )


def test_subsample_rows_deterministic_and_stratified():
    parent = _parent_table()
    a = subsample_rows(parent, n=30, seed=42)
    b = subsample_rows(parent, n=30, seed=42)
    assert a.equals(b)
    assert a.schema == contracts.SAMPLE
    counts = {
        s: int(n)
        for s, n in zip(
            *np.unique(
                a.column("stratum").to_numpy(zero_copy_only=False),
                return_counts=True,
            )
        )
    }
    assert counts == {"a": 18, "b": 9, "c": 3}
    parent_ids = set(parent.column("comment_id").to_pylist())
    assert set(a.column("comment_id").to_pylist()) <= parent_ids


def test_subsample_rows_rescaled_weights_sum_to_population():
    parent = _parent_table()
    sub = subsample_rows(parent, n=30, seed=42)
    sub_sum = float(sub.column("weight").to_numpy().sum())
    assert sub_sum == pytest.approx(PARENT_TOTAL, rel=1e-6)
    for stratum, (n_parent, w_parent) in STRATA.items():
        mask = pc_stratum(sub, stratum)
        assert sub.column("weight").to_numpy()[mask].sum() == pytest.approx(
            n_parent * w_parent, rel=1e-9
        )
    probs = sub.column("inclusion_prob").to_numpy()
    weights = sub.column("weight").to_numpy()
    assert np.allclose(probs * weights, 1.0)


def pc_stratum(table, stratum):
    return (
        table.column("stratum").to_numpy(zero_copy_only=False) == stratum
    )


def test_subsample_rows_seed_changes_draw():
    parent = _parent_table()
    a = subsample_rows(parent, n=30, seed=1)
    b = subsample_rows(parent, n=30, seed=2)
    assert sorted(a.column("comment_id").to_pylist()) != sorted(
        b.column("comment_id").to_pylist()
    )


def test_subsample_screen_writes_parquet_and_manifest(tmp_path, monkeypatch):
    _write_parent(tmp_path, monkeypatch)
    table = subsample_screen("parent", n=30, seed=7, out_id="robust-sub")
    assert table.num_rows == 30
    out = paths.sample_path("robust-sub")
    assert out.exists()
    assert pq.read_table(out).equals(table)
    meta = json.loads((paths.SAMPLES / "robust-sub.json").read_text())
    assert meta["parent_sample_id"] == "parent"
    assert meta["seed"] == 7
    assert meta["n"] == 30
    assert meta["frame_snapshot_id"] == "snap-x"
    assert set(meta["strata"]) == {"a", "b", "c"}
    copied = paths.MANIFESTS / "samples" / "robust-sub.json"
    assert copied.exists()


def test_subsample_items_deterministic_sorted(tmp_path):
    rows = [
        {
            "comment_id": 9_000_000_000 + i,
            "pain_sentence": f"pain {i}",
            "sentences": [f"pain {i}"],
        }
        for i in range(50)
    ]
    src = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), src)
    out1, out2 = tmp_path / "s1.parquet", tmp_path / "s2.parquet"
    t1 = subsample_items(src, n=10, seed=5, out=out1)
    t2 = subsample_items(src, n=10, seed=5, out=out2)
    assert t1.equals(t2)
    assert t1.num_rows == 10
    ids = t1.column("comment_id").to_pylist()
    assert ids == sorted(ids)
    assert t1.schema.names == ["comment_id", "pain_sentence", "sentences"]
    assert out1.exists() and out2.exists()


def test_subsample_items_caps_at_input(tmp_path):
    rows = [{"comment_id": 9_000_000_000 + i} for i in range(5)]
    src = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), src)
    t = subsample_items(src, n=100, seed=5, out=tmp_path / "s.parquet")
    assert t.num_rows == 5

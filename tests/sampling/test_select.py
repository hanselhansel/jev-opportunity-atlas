import hashlib
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.sampling.select import (
    SamplingError,
    allocate,
    collapse,
    draw,
    expand,
    resolve_strata,
    write_manifest,
)


def frame(n_a=600, n_b=300, n_c=100):
    ids = list(range(1, n_a + n_b + n_c + 1))
    strata = ["A"] * n_a + ["B"] * n_b + ["C"] * n_c
    return pa.table(
        {
            "comment_id": ids,
            "story_id": [i // 10 for i in ids],
            "stratum": strata,
        }
    )


def test_proportional_allocation_sums_exactly():
    assert allocate({"A": 600, "B": 300, "C": 100}, 101) == {"A": 61, "B": 30, "C": 10}


def test_min_per_stratum_is_honored_without_exceeding_size():
    alloc = allocate({"A": 600, "B": 300, "C": 2}, 50, min_per_stratum=5)
    assert alloc["C"] == 2 and sum(alloc.values()) == 50
    assert alloc["A"] == 32 and alloc["B"] == 16


def test_allocate_rejects_bad_n():
    with pytest.raises(ValueError):
        allocate({"A": 10}, -1)
    with pytest.raises(ValueError):
        allocate({"A": 10}, 11)
    with pytest.raises(ValueError):
        allocate({"A": 10, "B": 10}, 15, min_per_stratum=10)


def test_allocate_randomized_property():
    rng = np.random.default_rng(0)
    for _ in range(50):
        k = int(rng.integers(1, 8))
        sizes = {f"s{i}": int(rng.integers(1, 500)) for i in range(k)}
        n = int(rng.integers(0, sum(sizes.values()) + 1))
        m = int(rng.integers(0, 6))
        if sum(min(s, m) for s in sizes.values()) > n:
            with pytest.raises(ValueError):
                allocate(sizes, n, min_per_stratum=m)
            continue
        a = allocate(sizes, n, min_per_stratum=m)
        assert sum(a.values()) == n
        for h, s in sizes.items():
            assert 0 <= a[h] <= s
            assert a[h] >= min(s, m)


def test_draw_is_reproducible_and_weights_match():
    s1 = draw(frame(), n=100, seed=7, sample_id="s")
    s2 = draw(frame(), n=100, seed=7, sample_id="s")
    assert s1.column("comment_id").to_pylist() == s2.column("comment_id").to_pylist()
    rows = s1.to_pylist()
    a = [r for r in rows if r["stratum"] == "A"]
    assert len(a) == 60
    assert a[0]["inclusion_prob"] == pytest.approx(60 / 600)
    assert a[0]["weight"] == pytest.approx(10.0)
    assert sum(r["weight"] for r in rows) == pytest.approx(1000)
    assert {r["batch"] for r in rows} == {1}
    assert sorted(r["draw_order"] for r in rows) == list(range(100))


def test_different_seed_differs():
    a = draw(frame(), n=100, seed=7, sample_id="s").column("comment_id").to_pylist()
    b = draw(frame(), n=100, seed=8, sample_id="s").column("comment_id").to_pylist()
    assert a != b


def test_every_stratum_covered_or_collapsed():
    f = frame(n_a=600, n_b=300, n_c=3)
    s = draw(f, n=20, seed=1, sample_id="s")
    assert {r["stratum"] for r in s.to_pylist()} == {"A", "B", "C"}
    assert sum(r["weight"] for r in s.to_pylist()) == pytest.approx(903)


def test_n_larger_than_frame_raises():
    with pytest.raises(ValueError):
        draw(frame(), n=10_000, seed=1, sample_id="s")


def test_collapse_levels_and_resolution():
    f = pa.table(
        {
            "comment_id": list(range(1, 13)),
            "story_id": [1] * 12,
            "stratum": ["P01|story|e1"] * 3
            + ["P01|story|e2"] * 3
            + ["P01|ask_hn|e1"] * 3
            + ["P02|story|e1"] * 3,
        }
    )
    l1 = collapse(f, 1)
    assert set(l1.column("stratum").to_pylist()) == {"P01|story", "P01|ask_hn", "P02|story"}
    l2 = collapse(f, 2)
    assert set(l2.column("stratum").to_pylist()) == {"P01", "P02"}
    # n = 4 cannot give 4 strata 2 units each, nor 3 strata; collapse to periods.
    resolved, level = resolve_strata(f, n=4, min_per_stratum=2)
    assert level == 2
    s = draw(f, n=4, seed=3, sample_id="s", min_per_stratum=2)
    assert {r["stratum"] for r in s.to_pylist()} == {"P01", "P02"}
    assert sum(r["weight"] for r in s.to_pylist()) == pytest.approx(12)
    assert resolved.column("stratum").to_pylist() == l2.column("stratum").to_pylist()


def test_expand_adds_new_units_and_recomputes_probabilities():
    s1 = draw(frame(), n=100, seed=7, sample_id="s")
    s2 = expand(frame(), s1, extra=100, seed=8)
    ids = s2.column("comment_id").to_pylist()
    assert len(ids) == len(set(ids)) == 200
    rows = s2.to_pylist()
    a = [r for r in rows if r["stratum"] == "A"]
    assert len(a) == 120
    assert all(r["inclusion_prob"] == pytest.approx(120 / 600) for r in a)
    assert {r["batch"] for r in rows} == {1, 2}
    assert sum(r["weight"] for r in rows) == pytest.approx(1000)


def test_expand_reproducible_and_orders_continue():
    f = frame()
    s1 = draw(f, n=50, seed=7, sample_id="s")
    s2 = expand(f, s1, extra=50, seed=8)
    s3 = expand(f, s1, extra=50, seed=8)
    assert s2.column("comment_id").to_pylist() == s3.column("comment_id").to_pylist()
    new = [r for r in s2.to_pylist() if r["batch"] == 2]
    assert min(r["draw_order"] for r in new) == 50
    assert max(r["draw_order"] for r in new) == 99


def test_write_manifest_round_trip(tmp_path):
    table = draw(frame(), n=30, seed=5, sample_id="m1")
    meta = {
        "seed": 5,
        "seeds_by_batch": {"1": 5},
        "cutpoints": [3, 9],
        "frame_snapshot_id": "snap-x",
        "collapse_level": 0,
        "min_per_stratum": 2,
    }
    out = write_manifest(table, meta, tmp_path)
    parquet_path = tmp_path / "m1.parquet"
    json_path = tmp_path / "m1.json"
    assert parquet_path.exists() and json_path.exists()
    assert pq.read_table(parquet_path).equals(table)
    sidecar = json.loads(json_path.read_text())
    assert sidecar["sha256"] == hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    assert sidecar["n"] == 30 and sidecar["sample_id"] == "m1"
    assert sidecar["algorithm"].startswith("stratified SRSWOR")
    assert sidecar["strata"]["A"] == {"N_h": 600, "n_h": 18}
    assert out["sha256"] == sidecar["sha256"]


def test_sampling_error_is_value_error():
    assert issubclass(SamplingError, ValueError)

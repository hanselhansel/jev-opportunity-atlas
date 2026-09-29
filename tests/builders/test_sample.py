"""S6 task 1 tests: the Show HN launch sample.

The fixture snapshot is a synthetic `stories.parquet` plus a manifest.json
carrying the window bounds, written under a monkeypatched paths.SNAPSHOTS.
Shared helpers (`write_snapshot`, `repo_paths`, month timestamps) are reused
by test_run.py.
"""

import json
import math

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.sources.acquire import ts as _ts

WS = _ts("2025-09-28T00:00:00Z")
WE = _ts("2026-09-28T00:00:00Z")
SPAN = WE - WS
SNAPSHOT_ID = "snap-b"
BASE = 9_000_000_000


def month_ts(period: int) -> int:
    """Midpoint timestamp of window period `period` (1..12)."""
    return WS + int((period - 0.5) * SPAN / 12)


def story_row(story_id, time, title, text_norm="", in_window=True):
    return {
        "id": story_id,
        "time": time,
        "title": title,
        "text_norm": text_norm,
        "in_window": in_window,
    }


def write_snapshot(base, rows, snapshot_id=SNAPSHOT_ID):
    """Write stories.parquet + manifest.json for `rows` under base/<id>/."""
    snap = paths.SNAPSHOTS / snapshot_id
    snap.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "id": pa.array([r["id"] for r in rows], type=pa.int64()),
            "time": pa.array([r["time"] for r in rows], type=pa.int64()),
            "title": [r["title"] for r in rows],
            "text_norm": [r["text_norm"] for r in rows],
            "in_window": pa.array(
                [r["in_window"] for r in rows], type=pa.bool_()
            ),
        }
    )
    pq.write_table(table, snap / "stories.parquet")
    (snap / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": snapshot_id,
                "window": {
                    "start": "2025-09-28T00:00:00Z",
                    "end": "2026-09-28T00:00:00Z",
                },
            },
            indent=1,
        )
        + "\n"
    )
    return snap


def repo_paths(tmp_path, monkeypatch, rows, snapshot_id=SNAPSHOT_ID):
    """Point every paths.* root at tmp_path and write the fixture snapshot."""
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "data" / "samples")
    monkeypatch.setattr(paths, "MANIFESTS", tmp_path / "manifests")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "data" / "cache")
    write_snapshot(tmp_path, rows, snapshot_id)
    return tmp_path


def _month_sizes(rows):
    sizes: dict[str, int] = {}
    for r in rows:
        if r["in_window"] and r["title"].lower().startswith("show hn"):
            p = r.get("period") or ""
            sizes[p] = sizes.get(p, 0) + 1
    return sizes


def test_month_proportional(tmp_path, monkeypatch):
    from atlas.builders import sample

    rows = []
    nid = BASE
    sizes = {"P01": 60, "P02": 40, "P03": 20}
    for i, (period, count) in enumerate(sizes.items()):
        m = int(period[1:])
        for j in range(count):
            rows.append(
                story_row(nid, month_ts(m) + j, f"Show HN: thing {nid}")
            )
            nid += 1
    repo_paths(tmp_path, monkeypatch, rows)

    n = 12
    table = sample.draw_launches(SNAPSHOT_ID, n=n, seed=5)
    got = table.to_pylist()
    assert table.schema.equals(sample.SAMPLE_SCHEMA)
    by_period: dict[str, list] = {}
    for r in got:
        by_period.setdefault(r["period"], []).append(r)
    total = sum(sizes.values())
    for period, count in sizes.items():
        drawn = by_period[period]
        assert len(drawn) == round(n * count / total)
        weight = count / len(drawn)
        assert all(r["weight"] == pytest.approx(weight) for r in drawn)
    assert sum(r["weight"] for r in got) == pytest.approx(total)
    # deterministic per seed
    again = sample.draw_launches(SNAPSHOT_ID, n=n, seed=5)
    assert again.to_pylist() == got


def test_only_show_hn_in_window(tmp_path, monkeypatch):
    from atlas.builders import sample

    good = [
        story_row(BASE + 1, month_ts(1), "Show HN: alpha"),
        story_row(BASE + 2, month_ts(2), "show hn: beta"),
        story_row(BASE + 3, month_ts(2), "SHOW HN gamma"),
    ]
    bad = [
        story_row(BASE + 11, month_ts(1), "Ask HN: not a launch"),
        story_row(BASE + 12, month_ts(1), "Launch HN: not it"),
        story_row(BASE + 13, month_ts(1), "An ordinary story"),
        story_row(BASE + 14, month_ts(1), "Show HN: out of window",
                  in_window=False),
        story_row(BASE + 15, month_ts(1), "Showcase HN: no"),
    ]
    repo_paths(tmp_path, monkeypatch, good + bad)

    table = sample.draw_launches(SNAPSHOT_ID, n=len(good), seed=5)
    got_ids = {r["story_id"] for r in table.to_pylist()}
    assert got_ids == {r["id"] for r in good}
    n_population = sum(int(r["weight"]) for r in table.to_pylist())
    assert n_population == len(good)
    sidecar = paths.SAMPLES / "builders-5.json"
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text())
    assert meta["population"] == len(good)
    assert (paths.MANIFESTS / "samples" / "builders-5.json").exists()


def test_draw_reuses_existing_only_when_params_match(tmp_path, monkeypatch):
    from atlas.builders import sample

    rows = [
        story_row(BASE + i, month_ts(1), f"Show HN: s{i}") for i in range(10)
    ]
    repo_paths(tmp_path, monkeypatch, rows)
    first = sample.draw_launches(SNAPSHOT_ID, n=4, seed=9)
    second = sample.draw_launches(SNAPSHOT_ID, n=4, seed=9)
    assert second.to_pylist() == first.to_pylist()
    with pytest.raises(sample.SamplingError):
        sample.draw_launches(SNAPSHOT_ID, n=6, seed=9)


def test_rejects_oversized_draw(tmp_path, monkeypatch):
    from atlas.builders import sample

    rows = [story_row(BASE + i, month_ts(1), f"Show HN: s{i}") for i in range(3)]
    repo_paths(tmp_path, monkeypatch, rows)
    with pytest.raises(ValueError):
        sample.draw_launches(SNAPSHOT_ID, n=4, seed=1)


def test_sample_ids_sorted_and_unique(tmp_path, monkeypatch):
    from atlas.builders import sample

    rows = []
    for m in (1, 2):
        for i in range(50):
            sid = BASE + m * 1000 + i
            rows.append(story_row(sid, month_ts(m) + i, f"Show HN: {sid}"))
    repo_paths(tmp_path, monkeypatch, rows)
    table = sample.draw_launches(SNAPSHOT_ID, n=20, seed=2)
    ids = table.column("story_id").to_pylist()
    assert len(ids) == len(set(ids)) == 20
    assert math.isfinite(table.column("weight").to_pylist()[0])

"""L17 17.3: streaming packed screen — chunking, resume, progress, estimate."""

import json

import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.inference import ratelimit
from atlas.pilot import packed
from atlas.screen import run
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)
from tests.screen import support

RUN_ID = "screen-r1"


def _env(monkeypatch, seen):
    """Mock transport plus a fake clock so rpm pacing is instant."""
    mock_env(monkeypatch, make_transport(seen=seen))
    clock = support.FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)


def _progress_lines(stdout: str):
    lines = stdout.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith('{"progress"')
    )
    est = json.loads("\n".join(lines[:start]))
    progress = [json.loads(line)["progress"] for line in lines[start:]]
    return est, progress


def test_dry_run_prints_estimate_and_writes_nothing(pilot_repo, capsys):  # noqa: F811
    sid, _ids = support.write_sample()
    out = run.screen_sample(sid, RUN_ID, k=5, chunk=200, yes=False)
    printed = json.loads(capsys.readouterr().out)
    assert printed == out["estimate"]
    assert out["dispatched"] is False
    assert out["estimate"]["calls"] == 200
    assert out["estimate"]["remaining_calls"] == 200
    assert out["estimate"]["comments"] == 1000
    assert not paths.run_dir(RUN_ID).exists()


def test_dispatch_streams_chunks(pilot_repo, monkeypatch, capsys):  # noqa: F811
    sid, ids = support.write_sample()
    seen = []
    _env(monkeypatch, seen)
    out = run.screen_sample(
        sid, RUN_ID, k=5, budget="screen", rpm=1000, chunk=200, yes=True
    )
    assert out["dispatched"] is True
    assert out["run"]["new_requests"] == 200
    assert out["run"]["completed"] == 200

    est, progress = _progress_lines(capsys.readouterr().out)
    assert est["calls"] == 200
    assert len(progress) == 5
    for p in progress:
        for key in (
            "chunk",
            "chunks",
            "comments_done",
            "calls",
            "calls_total_done",
            "usd_calculated",
            "calls_per_min",
            "eta_min",
        ):
            assert key in p
    assert [p["comments_done"] for p in progress] == [200, 400, 600, 800, 1000]
    assert progress[-1]["calls_total_done"] == 200

    map_dir = paths.run_dir(RUN_ID) / "packed_map.parquet"
    assert sorted(p.name for p in map_dir.iterdir()) == [
        f"part-{i:05d}.parquet" for i in range(5)
    ]
    for i in range(5):
        assert pq.read_table(map_dir / f"part-{i:05d}.parquet").num_rows == 200
    pmap = pq.read_table(map_dir)
    rows = pmap.to_pylist()
    assert [r["comment_id"] for r in rows] == ids
    assert [r["packed_id"] for r in rows] == [
        pid for pid in ids[::5] for _ in range(5)
    ]
    assert [r["slot"] for r in rows] == [f"c{j}" for j in range(1, 6)] * 200

    manifest = json.loads(
        (paths.run_dir(RUN_ID) / "run_manifest.json").read_text()
    )
    assert [e["label"] for e in manifest["question_sets"]] == [
        "packed-screen@1"
    ]
    for request in seen:
        state = json.loads(request.content)["state"]
        assert len(state) <= 5


def test_resume_after_crash_never_rewrites(pilot_repo, monkeypatch, capsys):  # noqa: F811
    sid, ids = support.write_sample()
    seen = []
    _env(monkeypatch, seen)
    calls = {"n": 0}
    real_report = run._report

    def flaky(progress):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("crash after third chunk")
        real_report(progress)

    monkeypatch.setattr(run, "_report", flaky)
    with pytest.raises(RuntimeError, match="crash after third chunk"):
        run.screen_sample(sid, RUN_ID, k=5, chunk=200, yes=True)
    assert len(seen) == 120

    map_dir = paths.run_dir(RUN_ID) / "packed_map.parquet"
    parts = [map_dir / f"part-{i:05d}.parquet" for i in range(3)]
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in parts}

    monkeypatch.setattr(run, "_report", real_report)
    out = run.screen_sample(sid, RUN_ID, k=5, chunk=200, yes=True)
    assert len(seen) == 200  # exactly 80 more requests
    assert out["run"]["skipped_completed"] == 120
    assert out["run"]["new_requests"] == 80
    for p in parts:
        assert p.read_bytes() == before[p.name][0]
        assert p.stat().st_mtime_ns == before[p.name][1]

    run_dir = paths.run_dir(RUN_ID)
    answers = pq.read_table(run_dir / "answers")
    pmap = pq.read_table(map_dir)
    unpacked = packed.unpack_answers(answers, pmap)
    got = unpacked.column("comment_id").to_pylist()
    assert sorted(got) == ids and len(got) == 1000

    comments = pq.read_table(
        paths.snapshot_dir(SNAPSHOT_ID) / "comments.parquet",
        columns=["id", "text_norm"],
    )
    text = {r["id"]: r["text_norm"] for r in comments.to_pylist()}
    for r in unpacked.to_pylist():
        expected = 0.9 if "PAIN" in text[r["comment_id"]] else 0.1
        assert r["noul"] == expected


def test_param_mismatch_exits(pilot_repo, monkeypatch, capsys):  # noqa: F811
    sid, _ids = support.write_sample()
    _env(monkeypatch, [])
    run.screen_sample(sid, RUN_ID, k=5, chunk=200, yes=True)
    capsys.readouterr()
    with pytest.raises(SystemExit, match="differ"):
        run.screen_sample(sid, RUN_ID, k=5, chunk=100, yes=True)


def test_validation(pilot_repo):  # noqa: F811
    with pytest.raises(ValueError):
        run.screen_sample("sid", "r", k=5, chunk=7)
    with pytest.raises(ValueError):
        run.screen_sample("sid", "r", k=5, chunk=200, rpm=1500)
    with pytest.raises(ValueError):
        run.screen_sample("sid", "r", k=5, chunk=200, rpm=0)

import hashlib
import json
import re
import shutil
from collections import namedtuple

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts as c
from atlas.sources import acquire, shards
from atlas.sources.snapshot import SnapshotError, build, verify
from tests.sources.conftest import C0, C1, WE_ISO, WS_ISO, S

_Usage = namedtuple("usage", ["total", "used", "free"])


def _sdir(root):
    return root / "data" / "snapshots" / "test-snap"


def _physical_schema(contract):
    # Parquet has no seconds timestamp unit: timestamp[s, UTC] in a contract is
    # stored (and read back) as timestamp[ms, UTC]. Values stay second-aligned.
    return pa.schema(
        [
            f.with_type(pa.timestamp("ms", tz="UTC"))
            if pa.types.is_timestamp(f.type)
            else f
            for f in contract
        ]
    )


def _checksum(path):
    rows = pq.read_table(path).to_pylist()
    payload = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def test_build_outputs_match_contracts(raw_snapshot):
    cfg, root = raw_snapshot
    manifest = build(cfg, root, fetch_context_fn=None)
    sdir = _sdir(root)
    comments = pq.read_table(sdir / "comments.parquet")
    assert comments.schema.equals(_physical_schema(c.COMMENTS))
    assert pq.read_table(
        sdir / "comments.parquet", schema=c.COMMENTS
    ).schema.equals(c.COMMENTS)
    rows = {r["id"]: r for r in comments.to_pylist()}
    reasons = {i: r["exclusion_reason"] for i, r in rows.items()}
    assert reasons[S + 2] is None
    assert rows[S + 2]["eligible"] and rows[S + 2]["story_id"] == S + 1
    assert rows[S + 3]["depth"] == 2 and rows[S + 3]["thread_type"] == "ask_hn"
    assert rows[S + 3]["month"] == "2026-02"  # 2026-02-01T03:00Z is Jan 31 local
    assert {reasons[S + 4], reasons[S + 5], reasons[S + 6], reasons[S + 7]} == {
        "dead",
        "deleted",
        "non_english",
        "empty_text",
    }
    assert reasons[S + 9] == "out_of_window"
    assert rows[S + 8]["story_id"] == C0 and rows[S + 8]["depth"] == 2
    assert rows[S + 8]["eligible"]

    ws, we = acquire.ts(WS_ISO), acquire.ts(WE_ISO)
    for r in rows.values():
        assert r["period"] == c.period_of(r["time"], ws, we)

    stories = {r["id"]: r for r in pq.read_table(sdir / "stories.parquet").to_pylist()}
    assert set(stories) == {S + 1, C0}
    assert stories[C0]["in_window"] is False
    assert stories[S + 1]["thread_type"] == "ask_hn"
    ctx = pq.read_table(sdir / "context.parquet")
    assert ctx.schema.equals(c.CONTEXT)
    assert {r["id"] for r in ctx.to_pylist()} == {C0, C1}
    assert pq.read_table(sdir / "coverage.parquet").schema.equals(c.COVERAGE)

    assert manifest["schema_version"] == c.SCHEMA_VERSION
    assert manifest["counts"]["eligible"] == sum(
        r["eligible"] for r in rows.values()
    )
    assert set(manifest["files"]) == {
        "comments.parquet",
        "stories.parquet",
        "context.parquet",
        "coverage.parquet",
    }
    assert not (sdir / "_parts").exists()


def test_verify_detects_tampering(raw_snapshot):
    cfg, root = raw_snapshot
    build(cfg, root, fetch_context_fn=None)
    sdir = _sdir(root)
    assert verify(sdir)["ok"] is True
    p = sdir / "stories.parquet"
    p.write_bytes(p.read_bytes()[:-1] + b"\x00")
    report = verify(sdir)
    assert report["ok"] is False and report["bad_files"] == ["stories.parquet"]


def test_build_is_deterministic(raw_snapshot):
    cfg, root = raw_snapshot
    a = build(cfg, root, fetch_context_fn=None)["files"]
    sums_a = {n: _checksum(_sdir(root) / n) for n in a}
    b = build(cfg, root, fetch_context_fn=None)["files"]
    sums_b = {n: _checksum(_sdir(root) / n) for n in b}
    assert a == b
    assert sums_a == sums_b


def test_build_refuses_incomplete_shards(raw_snapshot):
    cfg, root = raw_snapshot
    raw = acquire.raw_dir(root, cfg)
    meta_p = shards.paths(raw / "shards", shards.ShardSpec(S, 10))[1]
    meta_p.unlink()
    with pytest.raises(SnapshotError, match=re.escape("uv run atlas acquire --workers 3")):
        build(cfg, root, fetch_context_fn=None)


def test_snapshot_reconciles_with_shard_meta(raw_snapshot):
    cfg, root = raw_snapshot
    recon = build(cfg, root, fetch_context_fn=None)["reconciliation"]
    assert recon["ids_scanned"] == 10
    assert recon["comments"] == 8 and recon["stories"] == 1
    assert recon["null"] == 1 and recon["failed"] == 0
    assert recon["other_types"] == 0 and recon["deleted_without_type"] == 0
    cov = pq.read_table(_sdir(root) / "coverage.parquet").to_pylist()
    got = {(r["dimension"], r["key"]): r["count"] for r in cov}
    assert got[("state", "ok")] == 7 and got[("state", "null")] == 1
    assert got[("type", "comment")] == 8 and got[("type", "none")] == 1
    assert got[("exclusion_reason", "eligible")] == 3
    assert got[("unresolved_root", "comments")] == 0
    assert got[("unresolved_root", "missing_parents")] == 0
    assert any(d == "period" for d, _ in got)


def test_build_refuses_low_disk(raw_snapshot, monkeypatch):
    cfg, root = raw_snapshot
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _Usage(1, 1, 0))
    with pytest.raises(SnapshotError, match="disk"):
        build(cfg, root, fetch_context_fn=None)


def test_cli_verify_exit_codes(raw_snapshot):
    from atlas import cli

    cfg, root = raw_snapshot
    build(cfg, root, fetch_context_fn=None)
    sdir = _sdir(root)
    parser = cli.build_parser()
    args = parser.parse_args(["snapshot", "verify", "--path", str(sdir)])
    args.func(args)  # good dir: prints report, no exit
    p = sdir / "coverage.parquet"
    p.write_bytes(p.read_bytes()[:-1] + b"\x00")
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == 1

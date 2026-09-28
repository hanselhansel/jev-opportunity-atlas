"""Tiny raw snapshot fixture: one complete shard of 10 records + context.jsonl.

All ids are >= 9_000_000_000 (synthetic fixture range). S is the shard start;
C0/C1 are ancestors outside the scanned range, served from context.jsonl.
"""

import hashlib
import json
from dataclasses import asdict

import pytest

from atlas import paths
from atlas.sources import acquire, shards
from atlas.sources.hn_api import FetchRecord

B = 9_000_000_000
S = B + 1_000  # shard start; shard covers S..S+9
C0 = B + 4  # story fetched as context (before the window)
C1 = B + 5  # comment fetched as context, parent of S+8

WS_ISO = "2025-09-28T00:00:00Z"
WE_ISO = "2026-09-28T00:00:00Z"
ENDED = "2026-09-20T00:00:00.000Z"


def _t(iso: str) -> int:
    from datetime import UTC, datetime

    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp())


def _rec(i: int, state: str, item, ended: str = ENDED) -> dict:
    return asdict(
        FetchRecord(
            id=i,
            state=state,
            http_status=200,
            attempts=1,
            backoff_s=0.0,
            started_at=ended,
            ended_at=ended,
            elapsed_ms=1.0,
            sha256=hashlib.sha256(str(i).encode()).hexdigest(),
            item=item,
        )
    )


def _comment(i, parent, time, text, **extra):
    return {
        "id": i,
        "type": "comment",
        "parent": parent,
        "time": time,
        "by": f"synthetic_user_{i % 7}",
        "text": text,
        **extra,
    }


@pytest.fixture
def raw_snapshot(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(paths, "DATA", root / "data")
    monkeypatch.setattr(paths, "RAW", root / "data" / "raw")
    monkeypatch.setattr(paths, "SNAPSHOTS", root / "data" / "snapshots")

    cfg = {
        "snapshot_id": "test-snap",
        "window_start": WS_ISO,
        "window_end": WE_ISO,
        "api_base": "https://x",
        "boundary_margin_ids": 0,
        "shard_size": 10,
        "concurrency": 4,
        "concurrent_shards": 1,
        "max_attempts": 2,
        "request_timeout_s": 5.0,
        "disk_headroom_gib": 0.0,
    }
    ws, we = _t(WS_ISO), _t(WE_ISO)
    raw = acquire.raw_dir(root, cfg)
    raw.mkdir(parents=True)
    (raw / "boundaries.json").write_text(
        json.dumps(
            {
                "window_start": WS_ISO,
                "window_end": WE_ISO,
                "maxitem_at_locate": S + 50,
                "first_id_in_window": S + 1,
                "last_id_in_window": S + 9,
                "scan_first_id": S,
                "scan_last_id": S + 9,
                "located_at": ENDED,
            }
        )
    )
    story = {
        "id": S + 1,
        "type": "story",
        "time": ws + 3600,
        "title": "Ask HN: Synthetic question about backups?",
        "text": "Synthetic story body about backup tooling choices.",
        "by": "synthetic_user_a",
        "score": 12,
        "descendants": 4,
        "url": "https://example.invalid/synthetic",
    }
    records = [
        _rec(S + 0, "null", None),
        _rec(S + 1, "ok", story),
        _rec(
            S + 2,
            "ok",
            _comment(
                S + 2,
                S + 1,
                ws + 7200,
                "Synthetic comment about backup tooling that I run every night.",
            ),
        ),
        _rec(
            S + 3,
            "ok",
            _comment(
                S + 3,
                S + 2,
                _t("2026-02-01T03:00:00Z"),  # month must be "2026-02" in UTC
                "Synthetic reply noting that nightly restores worked in the drill.",
            ),
        ),
        _rec(
            S + 4,
            "dead",
            _comment(
                S + 4,
                S + 1,
                ws + 8000,
                "Synthetic dead comment about restore tooling.",
                dead=True,
            ),
        ),
        _rec(
            S + 5,
            "deleted",
            {
                "id": S + 5,
                "type": "comment",
                "parent": S + 1,
                "time": ws + 9000,
                "deleted": True,
            },
        ),
        _rec(
            S + 6,
            "ok",
            _comment(
                S + 6,
                S + 1,
                ws + 10000,
                "Ich habe drei Stunden lang unsere Pipeline repariert "
                "und es war schlimm.",
            ),
        ),
        _rec(S + 7, "ok", _comment(S + 7, S + 1, ws + 11000, "")),
        _rec(
            S + 8,
            "ok",
            _comment(
                S + 8,
                C1,  # parent outside the scanned range, comes from context.jsonl
                ws + 12000,
                "Synthetic comment replying to an ancestor outside the scan.",
            ),
        ),
        _rec(
            S + 9,
            "ok",
            _comment(
                S + 9,
                S + 1,
                we + 3600,  # after the window
                "Synthetic comment posted after the window had ended entirely.",
            ),
        ),
    ]
    shards.write_shard(raw / "shards", shards.ShardSpec(S, 10), records, 1)

    ctx = raw / "context"
    ctx.mkdir()
    context_records = [
        _rec(
            C1,
            "ok",
            _comment(
                C1,
                C0,
                ws - 50_000,
                "Synthetic context comment text outside the scanned range.",
            ),
        ),
        _rec(
            C0,
            "ok",
            {
                "id": C0,
                "type": "story",
                "time": ws - 100_000,
                "title": "Synthetic old root story",
                "by": "synthetic_user_c",
                "score": 3,
                "descendants": 9,
            },
        ),
    ]
    (ctx / "context.jsonl").write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in context_records)
    )
    return cfg, root

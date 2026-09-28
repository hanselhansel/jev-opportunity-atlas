"""Fetch missing ancestor items into context.jsonl, walking up to the root.

Each round fetches the ids the resolver could not find in the scan range, then
queues the parents of fetched comments for the next round. The file is
append-only and resumable: ids already recorded with a non-failed state are
skipped, so a restarted build continues where it stopped.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Container
from pathlib import Path

from atlas.sources import hn_api

_SLEEP = asyncio.sleep


def _append_records(path: Path, records) -> None:
    with open(path, "a") as f:
        f.writelines(r.to_json() + "\n" for r in records)


def load_context(path: Path) -> dict[int, dict]:
    """Existing context.jsonl rows keyed by id; later lines win."""
    rows: dict[int, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["id"]] = r
    return rows


async def fetch_context(
    client,
    api_base: str,
    missing: set[int],
    out_dir: Path,
    concurrency: int,
    known: Container[int] | None = None,
) -> dict:
    """Fetch `missing` ids and their ancestors (comment parents) via the API.

    `known` marks ids that must never be fetched (e.g. the scanned range, which
    the CLI passes as a range object rather than a 4.5M-entry set). Returns
    {"fetched", "rounds", "failed"}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "context.jsonl"
    have = {i: r["state"] for i, r in load_context(path).items()}
    known = known if known is not None else ()
    attempted: set[int] = set()
    sem = asyncio.Semaphore(concurrency)
    fetched = rounds = failed = 0

    def done(i: int) -> bool:
        return i in attempted or i in known or (i in have and have[i] != "failed")

    todo = {i for i in missing if not done(i)}
    while todo:
        rounds += 1

        async def one(i):
            async with sem:
                return await hn_api.fetch_item(client, api_base, i, sleep=_SLEEP)

        records = await asyncio.gather(*(one(i) for i in sorted(todo)))
        _append_records(path, records)
        nxt: set[int] = set()
        for r in records:
            attempted.add(r.id)
            fetched += 1
            have[r.id] = r.state
            if r.state == "failed":
                failed += 1
                continue
            item = r.item or {}
            parent = item.get("parent")
            if (
                item.get("type") == "comment"
                and parent is not None
                and not done(parent)
            ):
                nxt.add(parent)
        todo = nxt
    return {"fetched": fetched, "rounds": rounds, "failed": failed}

"""`atlas discover search`: query HN Search (Algolia) inside the frozen window.

Hits are matched to the snapshot for frame status and written under
data/discovery/<name>/. Discovery-lane results are never used for prevalence.
Only comment IDs and timestamps are stored; comment text is never requested.
"""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from datetime import UTC, datetime

from atlas import paths

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_search(
    name: str,
    queries: list[str],
    snapshot_id: str | None = None,
    reason: str = "",
    config: str = "configs/acquisition.toml",
    transport=None,
    pause_s: float = 0.2,
) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from atlas.discovery.algolia import ALGOLIA_URL, search_all
    from atlas.discovery.match import match_hits
    from atlas.sources.acquire import ts

    cfg = tomllib.loads((paths.ROOT / config).read_text())
    if snapshot_id is None:
        snapshot_id = cfg["snapshot_id"]
    start, end = ts(cfg["window_start"]), ts(cfg["window_end"])

    snapshot_dir = paths.snapshot_dir(snapshot_id)
    if not (snapshot_dir / "comments.parquet").exists():
        raise SystemExit(
            f"snapshot {snapshot_id!r} has no comments.parquet under "
            f"{snapshot_dir}; build the snapshot first"
        )

    hit_rows: list[dict] = []
    log_rows: list[dict] = []
    per_query: dict[str, int] = {}
    for query in queries:
        out = asyncio.run(
            search_all(query, start, end, transport=transport, pause_s=pause_s)
        )
        log_rows.extend(out["requests"])
        by_id = {int(h["objectID"]): h for h in out["hits"]}
        per_query[query] = len(by_id)
        for hit_id in sorted(by_id):
            h = by_id[hit_id]
            hit_rows.append(
                {
                    "id": hit_id,
                    "created_at_i": int(h["created_at_i"]),
                    "story_id": (
                        int(h["story_id"])
                        if h.get("story_id") is not None
                        else None
                    ),
                    "query": query,
                    "lane": "discovery",
                }
            )

    unique_ids = sorted({r["id"] for r in hit_rows})
    frame = match_hits(unique_ids, snapshot_dir)
    status: dict[int, str] = {}
    for bucket in ("in_frame", "outside_frame", "ineligible"):
        for hit_id in frame[bucket]:
            status[hit_id] = bucket
    for row in hit_rows:
        row["frame"] = status[row["id"]]

    out_dir = paths.DISCOVERY / name
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("created_at_i", pa.int64()),
            ("story_id", pa.int64()),
            ("query", pa.string()),
            ("lane", pa.string()),
            ("frame", pa.string()),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(hit_rows, schema=schema), out_dir / "hits.parquet"
    )
    with open(out_dir / "requests.jsonl", "w") as f:
        for row in log_rows:
            f.write(json.dumps(row) + "\n")
    manifest = {
        "name": name,
        "lane": "discovery",
        "endpoint": ALGOLIA_URL,
        "queries": list(queries),
        "reason": reason,
        "snapshot_id": snapshot_id,
        "window": {
            "start": cfg["window_start"],
            "end": cfg["window_end"],
            "start_ts": start,
            "end_ts": end,
        },
        "created_at": _utc_now(),
        "counts": {
            "requests": len(log_rows),
            "hit_rows": len(hit_rows),
            "unique_ids": len(unique_ids),
            "in_frame": len(frame["in_frame"]),
            "outside_frame": len(frame["outside_frame"]),
            "ineligible": len(frame["ineligible"]),
            "per_query": per_query,
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def _search(args) -> None:
    if not SLUG.fullmatch(args.name):
        raise SystemExit(
            f"invalid --name {args.name!r}: use lowercase letters, digits, "
            "and dashes, starting with a letter or digit"
        )
    manifest = run_search(
        name=args.name,
        queries=args.query,
        snapshot_id=args.snapshot,
        reason=args.reason,
        config=args.config,
    )
    print(json.dumps(manifest, indent=1))


def register(sub) -> None:
    d = sub.add_parser(
        "discover",
        help="Discovery-lane Algolia search (never used for prevalence)",
    )
    dsub = d.add_subparsers(dest="discover_cmd", required=True)
    s = dsub.add_parser(
        "search", help="Search HN comments inside the frozen window"
    )
    s.add_argument("--name", required=True, help="Slug for data/discovery/<name>/")
    s.add_argument("--query", action="append", required=True)
    s.add_argument("--snapshot", default=None)
    s.add_argument("--reason", default="")
    s.add_argument("--config", default="configs/acquisition.toml")
    s.set_defaults(func=_search)

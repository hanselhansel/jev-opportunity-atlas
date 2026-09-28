"""`atlas timeline mark <event>`: append a named, timestamped event to runs/timeline.jsonl.

Used for time-to-first-finding and phase boundaries in the cost and time report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime


def mark(event: str, note: str = "") -> dict:
    from atlas import paths

    row = {"event": event, "at": datetime.now(UTC).isoformat(timespec="seconds"), "note": note}
    paths.RUNS.mkdir(parents=True, exist_ok=True)
    with open(paths.RUNS / "timeline.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def _cmd(args) -> None:
    print(json.dumps(mark(args.event, args.note)))


def register(sub) -> None:
    t = sub.add_parser("timeline", help="Record project timeline events")
    tsub = t.add_subparsers(dest="timeline_cmd", required=True)
    m = tsub.add_parser("mark", help="Append a named event with the current UTC time")
    m.add_argument("event")
    m.add_argument("--note", default="")
    m.set_defaults(func=_cmd)

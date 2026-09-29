"""S5 tally: per-tool and per-card named-fix counts for story.json.

A problem-comment mention counts as `complaint`; a reply or follow-up
mention counts as `fix` only when Jev confirmed `recommends` (the hit_id is
in `confirmed`). `threads` counts distinct story_ids with a counted
mention. `fix_share = fix_threads / (fix_threads + complaint_threads)` with
a stratified thread-bootstrap interval (strata = phase-2 stratum, clusters
= story_id, R = 1000, seed 0, via atlas.sitedata.build_share.boot_totals).
A tool named in fewer than 10 counted threads stays in the tallies marked
`sparse`; a tool with only denied reply mentions shows `threads` 0 and a
null fix_share. Est follows the story.v1 contract shape.

`hit_id` is re-exported from confirm so mention rows can be built and
joined in one place.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.sitedata.build_share import boot_totals
from atlas.solutions.confirm import hit_id

__all__ = ["MENTIONS", "hit_id", "tally", "write_mentions", "write_tallies"]

SPARSE_THREADS = 10
N_BOOT = 1000
SEED = 0
_KIND_ORDER = {"problem": 0, "reply": 1, "followup": 2}
_FIX_KINDS = frozenset({"reply", "followup"})

# IDs and tool names only; no text, no authors (master plan constraint).
MENTIONS = pa.schema(
    [
        ("hit_id", pa.int64()),
        ("comment_id", pa.int64()),
        ("problem_id", pa.int64()),
        ("card_id", pa.string()),
        ("story_id", pa.int64()),
        ("kind", pa.string()),
        ("tool", pa.string()),
        ("time", pa.int64()),
    ]
)


def _sorted_mentions(mentions):
    return sorted(
        mentions,
        key=lambda m: (
            m["tool"],
            m["story_id"] if m["story_id"] is not None else -1,
            _KIND_ORDER.get(m["kind"], 9),
            m["comment_id"],
        ),
    )


def _fix_share_est(per_thread, n_boot, seed):
    """Est for fix_threads/(fix_threads+complaint_threads).

    `per_thread` is one (stratum, fix_flag, complaint_flag) triple per
    distinct thread. The point estimate and every replicate count a thread
    once per role, so a thread that both blames and fixes counts in both.
    """
    n = len(per_thread)
    fix = sum(1 for _s, f, _c in per_thread if f)
    complaint = sum(1 for _s, _f, c in per_thread if c)
    if fix + complaint == 0:
        return None
    est = fix / (fix + complaint)
    cols = np.array([[float(f), float(c)] for _s, f, c in per_thread])
    total = boot_totals(
        cols,
        [s for s, _f, _c in per_thread],
        [i for i, _t in enumerate(per_thread)],
        n_boot=n_boot,
        seed=seed,
    )
    denom = total[:, 0] + total[:, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        reps = np.where(denom > 0, total[:, 0] / denom, np.nan)
    lo95, lo50, hi50, hi95 = (
        float(v) for v in np.nanquantile(reps, [0.025, 0.25, 0.75, 0.975])
    )
    return {
        "est": est,
        "lo50": lo50,
        "hi50": hi50,
        "lo95": lo95,
        "hi95": hi95,
        "n": n,
        "sparse": n < SPARSE_THREADS,
    }


def _per_thread(rows):
    """Collapse a tool's mention rows to one (stratum, fix, complaint) per
    thread; stratum is the row's first in deterministic order."""
    by_thread: dict[int, list] = {}
    for m in _sorted_mentions(rows):
        cluster = m["story_id"] if m["story_id"] is not None else -m["comment_id"]
        entry = by_thread.setdefault(cluster, [m["stratum"], False, False])
        if m["kind"] == "problem":
            entry[2] = True  # complaint
        else:
            entry[1] = True  # confirmed fix
    return [(s, f, c) for s, f, c in by_thread.values()]


def tally(mentions, confirmed, tools, n_boot=N_BOOT, seed=SEED):
    """(tools_rows, card_tools) matching story.v1 `tools`/`cards[].tools`.

    `mentions`: dicts with hit_id, comment_id, problem_id, card_id,
    story_id, stratum, kind, tool. `confirmed`: set of hit_ids Jev
    confirmed. `tools`: list[match.Tool] for the category column.
    """
    categories = {t.name: t.category for t in tools}
    by_tool: dict[str, list] = defaultdict(list)
    for m in mentions:
        by_tool[m["tool"]].append(m)

    tools_rows = []
    for name in sorted(by_tool):
        rows = by_tool[name]
        complaint_rows = [m for m in rows if m["kind"] == "problem"]
        fix_rows = [
            m
            for m in rows
            if m["kind"] in _FIX_KINDS and m["hit_id"] in confirmed
        ]
        complaint_threads = {
            m["story_id"] for m in complaint_rows if m["story_id"] is not None
        }
        fix_threads = {
            m["story_id"] for m in fix_rows if m["story_id"] is not None
        }
        counted = complaint_rows + fix_rows
        threads = {
            m["story_id"] for m in counted if m["story_id"] is not None
        }
        per_thread = _per_thread(counted)
        tools_rows.append(
            {
                "name": name,
                "category": categories.get(name, ""),
                "threads": len(threads),
                "fix_threads": len(fix_threads),
                "complaint_threads": len(complaint_threads),
                "fix_share": _fix_share_est(per_thread, n_boot, seed),
                "sparse": len(threads) < SPARSE_THREADS,
            }
        )
    tools_rows.sort(key=lambda r: (-r["threads"], r["name"]))

    card_tools: dict[str, dict] = {}
    per_card: dict[str, dict] = defaultdict(
        lambda: {"fixes": defaultdict(set), "blamed": defaultdict(set)}
    )
    for m in mentions:
        card = m["card_id"]
        if not card:
            continue
        if m["kind"] == "problem":
            per_card[card]["blamed"][m["tool"]].add(m["story_id"])
        elif m["hit_id"] in confirmed:
            per_card[card]["fixes"][m["tool"]].add(m["story_id"])
    for card in sorted(per_card):
        buckets = per_card[card]
        card_tools[card] = {
            key: [
                {"name": name, "threads": len(story_ids)}
                for name, story_ids in sorted(
                    buckets[key].items(), key=lambda kv: (-len(kv[1]), kv[0])
                )
            ]
            for key in ("fixes", "blamed")
        }
    return tools_rows, card_tools


def write_mentions(mentions, path) -> Path:
    """mentions.parquet: IDs and tool names only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [{k: m.get(k) for k in MENTIONS.names} for m in mentions],
        schema=MENTIONS,
    )
    pq.write_table(table, path)
    return path


def write_tallies(path, tools_rows, card_tools, meta) -> Path:
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**meta, "tools": tools_rows, "cards_tools": card_tools}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path

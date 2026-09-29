"""Second-wave expansion of the phase-2 facet sample (L27).

Within a stratum, an SRSWOR of n followed by an SRSWOR of m drawn from the
remaining units is an SRSWOR of n+m. ``expand_phase2`` therefore keeps every
row of an existing phase-2 sample, tops each positive stratum up to the new
``allocate_capped`` target, and recomputes ``p2 = (n_old_h + m_h) / N_h``
and ``weight = w1 / p2`` for every selected positive row. Below-cutoff check
rows are copied unchanged. A ``wave`` column marks base rows (1) and added
rows (2).
"""

from __future__ import annotations

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.facets.phase2 import PHASE2_SCHEMA, allocate_capped

EXPANDED_SCHEMA = pa.schema([*PHASE2_SCHEMA, pa.field("wave", pa.int8())])


def expand_phase2(
    screen_run: str,
    base_sample_id: str,
    new_sample_id: str,
    *,
    n_pos: int,
    seed: int,
) -> pa.Table:
    """Grow ``base_sample_id``'s positive rows to the ``n_pos`` target.

    Writes ``<new_sample_id>.parquet`` plus its JSON manifest under
    ``paths.SAMPLES`` and returns the expanded table.
    """
    meta = json.loads(
        (paths.SAMPLES / f"{base_sample_id}.json").read_text()
    )
    parent = meta.get("parent_run")
    if parent is not None and parent != screen_run:
        raise ValueError(
            f"base sample {base_sample_id} came from screen run "
            f"{parent!r}, not {screen_run!r}"
        )
    cutoff = meta["cutoff"]
    base = pq.read_table(paths.sample_path(base_sample_id)).to_pylist()
    screen = pq.read_table(
        paths.run_dir(screen_run) / "screen_by_comment.parquet"
    ).to_pylist()

    pos = [r for r in screen if r["firsthand_p"] >= cutoff]
    by: dict[str, list] = {}
    for r in pos:
        by.setdefault(r["stratum"], []).append(r)
    wsum = {h: sum(r["weight"] for r in rs) for h, rs in by.items()}
    target = allocate_capped(wsum, {h: len(rs) for h, rs in by.items()}, n_pos)

    pos_ids = {r["comment_id"] for r in pos}
    old: dict[str, set] = {}
    neg_rows = []
    for r in base:
        if r["phase"] == "pos":
            if r["comment_id"] not in pos_ids:
                raise ValueError(
                    f"base row {r['comment_id']} is not a positive in "
                    f"{screen_run}'s screen table"
                )
            old.setdefault(r["stratum"], set()).add(r["comment_id"])
        else:
            neg_rows.append(r)

    rng = np.random.default_rng(seed)
    out, added = [], 0
    for h in sorted(by):
        rs = sorted(by[h], key=lambda r: r["comment_id"])
        old_ids = old.get(h, set())
        remaining = [r for r in rs if r["comment_id"] not in old_ids]
        m = min(max(0, target.get(h, 0) - len(old_ids)), len(remaining))
        idx = rng.choice(len(remaining), m, replace=False)
        new_ids = {remaining[i]["comment_id"] for i in idx}
        p2 = (len(old_ids) + m) / len(rs)
        for r in rs:
            cid = r["comment_id"]
            if cid in old_ids:
                wave = 1
            elif cid in new_ids:
                wave = 2
            else:
                continue
            out.append(
                {
                    "comment_id": cid,
                    "story_id": r["story_id"],
                    "stratum": h,
                    "half": r["half"],
                    "phase": "pos",
                    "w1": r["weight"],
                    "p2": p2,
                    "weight": r["weight"] / p2,
                    "firsthand_p": r["firsthand_p"],
                    "wave": wave,
                }
            )
        added += m
    for r in neg_rows:
        out.append({k: r[k] for k in PHASE2_SCHEMA.names} | {"wave": 1})

    tbl = pa.Table.from_pylist(out, schema=EXPANDED_SCHEMA)
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    pq.write_table(tbl, paths.sample_path(new_sample_id))
    (paths.SAMPLES / f"{new_sample_id}.json").write_text(
        json.dumps(
            {
                "sample_id": new_sample_id,
                "base_sample_id": base_sample_id,
                "seed": seed,
                "parent_run": screen_run,
                "cutoff": cutoff,
                "n_pos_target": n_pos,
                "added": {"pos": added, "neg": 0},
                "n_pos": sum(r["phase"] == "pos" for r in out),
                "n_neg": len(neg_rows),
                "snapshot_id": meta["snapshot_id"],
                "design": (
                    "expanded two-phase: within a stratum, an SRSWOR of n "
                    "followed by an SRSWOR of m from the remaining units is "
                    "an SRSWOR of n+m; p2 = (n_old_h + m_h) / N_h; final "
                    "weight w1/p2; wave 1 = base, 2 = added"
                ),
            },
            indent=1,
        )
        + "\n"
    )
    return tbl

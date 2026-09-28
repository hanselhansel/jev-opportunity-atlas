"""Sampling frame: eligible comments labelled f"{period}|{thread_type}|{tier}"."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc


def engagement_cutpoints(descendants: list[int]) -> tuple[int, int]:
    """Lower-tercile cutpoints over `descendants` of stories with eligible comments."""
    vals = np.asarray(descendants, dtype=np.float64)
    lo, hi = np.quantile(vals, [1 / 3, 2 / 3], method="lower")
    return int(lo), int(hi)


def _str(column) -> np.ndarray:
    return pc.fill_null(column, "").to_numpy(zero_copy_only=False).astype(str)


def build_frame(
    comments: pa.Table, stories: pa.Table, cutpoints: tuple[int, int]
) -> pa.Table:
    """Eligible comments only, columns comment_id, story_id, stratum, sorted by id.

    Engagement tier from the story's `descendants`: e1 <= lo, e2 <= hi, else e3.
    Tier e0 when story_id is null, the story is absent, or descendants is null.
    """
    lo, hi = cutpoints
    frame = comments.filter(pc.equal(comments.column("eligible"), True))
    idx = pc.index_in(frame.column("story_id"), value_set=stories.column("id"))
    desc = (
        pc.take(stories.column("descendants"), idx)
        .to_numpy(zero_copy_only=False)
        .astype(np.float64)
    )
    tier = np.full(frame.num_rows, "e3", dtype="U2")
    tier[desc <= hi] = "e2"
    tier[desc <= lo] = "e1"
    tier[np.isnan(desc)] = "e0"
    labels = np.char.add(
        np.char.add(_str(frame.column("period")), "|"),
        np.char.add(_str(frame.column("thread_type")), "|"),
    )
    labels = np.char.add(labels, tier)
    order = np.argsort(
        frame.column("id").to_numpy(zero_copy_only=False), kind="stable"
    )
    return pa.table(
        {
            "comment_id": pa.array(
                frame.column("id").to_numpy(zero_copy_only=False)[order],
                type=pa.int64(),
            ),
            "story_id": pc.take(frame.column("story_id"), pa.array(order)),
            "stratum": pa.array(labels[order], type=pa.string()),
        }
    )

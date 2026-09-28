"""Find the ID range of a UTC time window on the official HN API.

HN IDs increase roughly with creation time. We binary-search for the first ID
whose `time` >= a target. IDs without a time (null responses) are skipped by
probing forward. Callers add a margin because ordering is not guaranteed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from atlas.sources.hn_api import FetchRecord

Fetch = Callable[[int], Awaitable[FetchRecord]]


async def time_at(
    fetch: Fetch, item_id: int, max_skip: int = 200
) -> tuple[int, int] | None:
    """(id, time) of the first item at or after item_id that has a time."""
    for probe in range(item_id, item_id + max_skip):
        rec = await fetch(probe)
        if rec.item and "time" in rec.item:
            return probe, rec.item["time"]
    return None


async def first_id_at_or_after(fetch: Fetch, target_ts: int, lo: int, hi: int) -> int:
    """Smallest id in [lo, hi] whose (skip-forward) time >= target_ts."""
    while lo < hi:
        mid = (lo + hi) // 2
        found = await time_at(fetch, mid)
        if found is None or found[1] >= target_ts:
            hi = mid
        else:
            lo = found[0] + 1
    return lo

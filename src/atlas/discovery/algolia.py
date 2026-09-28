"""HN Search (Algolia) client for the discovery lane.

Algolia caps any single query at 1,000 hits, so `search_all` halves the time
range until every slice fits under the cap. Every request (retries and
abandoned slices included) is appended to a log returned next to the deduped
hits. Only IDs are requested; comment text is never fetched.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime

import httpx

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
ATTRIBUTES = "objectID,created_at_i,story_id,parent_id"
MAX_HITS = 1000


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _backoff_s(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return 1.0 * 2 ** (attempt - 1)


async def search_all(
    query: str,
    lo: int,
    hi: int,
    transport=None,
    per_page: int = 1000,
    pause_s: float = 0.2,
    max_attempts: int = 6,
    sleep=asyncio.sleep,
) -> dict:
    """Collect every hit for `query` in [lo, hi), splitting slices as needed."""
    hits: list[dict] = []
    requests: list[dict] = []
    last_start = 0.0

    async with httpx.AsyncClient(transport=transport, timeout=20.0) as client:

        async def get_page(slo: int, shi: int, page: int) -> tuple[dict, list[dict]]:
            """Fetch one page with retries. Returns (payload, attempt log rows)."""
            nonlocal last_start
            rows: list[dict] = []
            for attempt in range(1, max_attempts + 1):
                gap = pause_s - (time.monotonic() - last_start)
                if gap > 0:
                    await sleep(gap)
                last_start = time.monotonic()
                row = {
                    "query": query,
                    "lo": slo,
                    "hi": shi,
                    "page": page,
                    "attempt": attempt,
                    "status": None,
                    "n_hits": None,
                    "retrieved_at": _utc_now(),
                    "sha256": None,
                    "used": False,
                    "truncated": False,
                }
                rows.append(row)
                retry_after = None
                try:
                    resp = await client.get(
                        ALGOLIA_URL,
                        params={
                            "query": query,
                            "tags": "comment",
                            "numericFilters": (
                                f"created_at_i>={slo},created_at_i<{shi}"
                            ),
                            "hitsPerPage": per_page,
                            "page": page,
                            "attributesToRetrieve": ATTRIBUTES,
                        },
                    )
                except httpx.TransportError:
                    status = None
                    retryable = True
                    delay = 1.0 * 2 ** (attempt - 1)
                else:
                    status = resp.status_code
                    row["status"] = status
                    row["sha256"] = hashlib.sha256(resp.content).hexdigest()
                    if status == 200:
                        payload = resp.json()
                        row["n_hits"] = payload.get("nbHits")
                        return payload, rows
                    retryable = status in RETRYABLE_STATUS
                    retry_after = resp.headers.get("Retry-After")
                    delay = _backoff_s(attempt, retry_after)
                if not retryable or attempt == max_attempts:
                    raise RuntimeError(
                        f"algolia search failed: query={query!r} "
                        f"range=[{slo},{shi}) page={page} status={status}"
                    )
                await sleep(delay)
            raise RuntimeError(
                f"algolia search failed: query={query!r} "
                f"range=[{slo},{shi}) page={page} status=None"
            )

        async def collect(slo: int, shi: int) -> None:
            payload, rows = await get_page(slo, shi, 0)
            n_hits = payload.get("nbHits") or 0
            if n_hits >= MAX_HITS and shi - slo > 1:
                requests.extend(rows)
                mid = (slo + shi) // 2
                await collect(slo, mid)
                await collect(mid, shi)
                return
            rows[-1]["used"] = True
            if n_hits >= MAX_HITS:
                rows[-1]["truncated"] = True
            requests.extend(rows)
            hits.extend(payload.get("hits") or [])
            for page in range(1, int(payload.get("nbPages") or 1)):
                payload, rows = await get_page(slo, shi, page)
                rows[-1]["used"] = True
                requests.extend(rows)
                hits.extend(payload.get("hits") or [])

        await collect(lo, hi)

    deduped: dict[str, dict] = {}
    for h in hits:
        deduped.setdefault(h["objectID"], h)
    return {"hits": list(deduped.values()), "requests": requests}

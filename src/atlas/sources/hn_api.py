"""Official HN API client: one item per request, every attempt recorded.

Each fetch returns a FetchRecord that is written verbatim into a shard. The
record is built from an explicit field list, so nothing credential-bearing or
SDK-internal can leak into stored logs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class FetchRecord:
    id: int
    state: str  # ok | deleted | dead | null | failed
    http_status: int | None
    attempts: int
    backoff_s: float
    started_at: str
    ended_at: str
    elapsed_ms: float
    sha256: str | None  # of the raw response body bytes
    item: dict[str, Any] | None
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)


def classify(item: dict[str, Any] | None) -> str:
    if item is None:
        return "null"
    if item.get("deleted"):
        return "deleted"
    if item.get("dead"):
        return "dead"
    return "ok"


class Getter(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


async def fetch_item(
    client: Getter,
    api_base: str,
    item_id: int,
    max_attempts: int = 6,
    base_backoff_s: float = 1.0,
    sleep=asyncio.sleep,
) -> FetchRecord:
    url = f"{api_base}/item/{item_id}.json"
    started_at = utc_now()
    t0 = time.monotonic()
    errors: list[str] = []
    backoff_total = 0.0
    status: int | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.get(url)
            status = resp.status_code
            if status == 200:
                body = resp.content
                item = json.loads(body) if body else None
                return FetchRecord(
                    id=item_id,
                    state=classify(item),
                    http_status=status,
                    attempts=attempt,
                    backoff_s=round(backoff_total, 3),
                    started_at=started_at,
                    ended_at=utc_now(),
                    elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
                    sha256=hashlib.sha256(body).hexdigest(),
                    item=item,
                    errors=errors,
                )
            errors.append(f"http_{status}")
            if status not in RETRYABLE_STATUS:
                break
        except (httpx.TransportError, json.JSONDecodeError) as exc:
            errors.append(type(exc).__name__)
        if attempt < max_attempts:
            delay = base_backoff_s * (2 ** (attempt - 1))
            backoff_total += delay
            await sleep(delay)
    return FetchRecord(
        id=item_id,
        state="failed",
        http_status=status,
        attempts=len(errors),
        backoff_s=round(backoff_total, 3),
        started_at=started_at,
        ended_at=utc_now(),
        elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
        sha256=None,
        item=None,
        errors=errors,
    )


def make_client(concurrency: int, timeout_s: float) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=concurrency, max_keepalive_connections=concurrency
    )
    return httpx.AsyncClient(
        timeout=timeout_s,
        limits=limits,
        headers={
            "User-Agent": "jev-opportunity-atlas/0.1 (research; github.com/hanselhansel)"
        },
    )

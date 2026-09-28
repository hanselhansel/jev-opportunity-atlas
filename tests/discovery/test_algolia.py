"""Algolia discovery client: slicing, retries, paging, request log."""

import asyncio
import re

import httpx

from atlas.discovery.algolia import search_all

BASE = 9_000_000_000


def make_transport(total_by_slice):
    calls = []

    def handler(request):
        params = dict(request.url.params)
        m = re.fullmatch(
            r"created_at_i>=(\d+),created_at_i<(\d+)", params["numericFilters"]
        )
        lo, hi = int(m.group(1)), int(m.group(2))
        n = sum(1 for t in total_by_slice if lo <= t < hi)
        hits = [
            {"objectID": str(BASE + t), "created_at_i": t}
            for t in total_by_slice
            if lo <= t < hi
        ][:1000]
        calls.append((lo, hi))
        return httpx.Response(200, json={"nbHits": n, "hits": hits, "nbPages": 1})

    return httpx.MockTransport(handler), calls


def test_slices_until_each_query_fits():
    times = list(range(3000))  # 3000 hits over [0, 3000)
    transport, _calls = make_transport(times)
    out = asyncio.run(search_all("stripe payouts", 0, 3000, transport=transport))
    assert sorted(int(h["objectID"]) for h in out["hits"]) == [
        BASE + t for t in times
    ]
    assert all(r["n_hits"] < 1000 for r in out["requests"] if r["used"])
    assert {"query", "lo", "hi", "status", "n_hits", "retrieved_at", "sha256"} <= set(
        out["requests"][0]
    )


def test_retries_429_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "nbHits": 1,
                "hits": [{"objectID": str(BASE + 1), "created_at_i": 5}],
                "nbPages": 1,
            },
        )

    delays = []

    async def fake_sleep(s):
        delays.append(s)

    out = asyncio.run(
        search_all(
            "q",
            0,
            10,
            transport=httpx.MockTransport(handler),
            pause_s=0,
            sleep=fake_sleep,
        )
    )
    assert [int(h["objectID"]) for h in out["hits"]] == [BASE + 1]
    assert len(out["requests"]) == 2
    first, second = out["requests"]
    assert first["status"] == 429 and first["used"] is False
    assert second["status"] == 200 and second["used"] is True
    assert delays == [0.0]


def test_fetches_extra_pages():
    hits = [
        {"objectID": str(BASE + i), "created_at_i": i} for i in range(5)
    ]

    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "nbHits": 5,
                "hits": hits[page * 2 : page * 2 + 2],
                "nbPages": 3,
            },
        )

    out = asyncio.run(
        search_all(
            "q",
            0,
            10,
            transport=httpx.MockTransport(handler),
            per_page=2,
            pause_s=0,
        )
    )
    assert [int(h["objectID"]) for h in out["hits"]] == [BASE + i for i in range(5)]
    used = [r for r in out["requests"] if r["used"]]
    assert len(used) == 3
    assert [r["page"] for r in used] == [0, 1, 2]

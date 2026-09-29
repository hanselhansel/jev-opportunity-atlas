"""Requests-per-minute limiter: token bucket pacing in the runner (L17 17.1).

The fake clock only advances when the bucket sleeps, so request times recorded
in the transport land exactly on bucket boundaries.
"""

import asyncio

import pytest

from atlas.inference import ratelimit
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient, RetryPolicy
from atlas.inference.questions import load_question_set
from atlas.inference.runner import RunContext, run_batch
from tests.inference.mock_jev import make_transport

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64
PRICE = 0.042e-6


class FakeClock:
    """Integer-nanosecond clock so sleeps land exactly on lattice points."""

    def __init__(self):
        self.ns = 0

    def now(self):
        return self.ns / 1e9

    async def sleep(self, delay):
        self.ns += round(delay * 1e9)
        await asyncio.sleep(0)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)
    return clock


def _max_per_second(times):
    ordered = sorted(times)
    return max(
        sum(1 for t in ordered if s <= t < s + 1.0) for s in ordered
    )


def items(n):
    return [
        {
            "comment_id": i,
            "comment": f"text {i}",
            "parent": "",
            "story_title": "T",
            "thread_type": "story",
            "sentences": [f"text {i}"],
        }
        for i in range(n)
    ]


def _ctx(tmp_path, script, clock, times, rpm=600, concurrency=16):
    def on_request(_n, _request):
        times.append(clock.now())

    client = JevClient(
        api_key=CANARY,
        base="http://mock",
        transport=make_transport(script, on_request=on_request),
        policy=RetryPolicy(backoff_initial=0, backoff_max=0),
    )
    guard = BudgetGuard(
        cap_usd=1.0, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000
    )
    return RunContext(
        run_id="r1",
        run_dir=tmp_path / "r1",
        client=client,
        guard=guard,
        model="jev-1.13.0",
        price_version="typesafe-2026-09-28",
        cache_path=tmp_path / "cache.sqlite",
        concurrency=concurrency,
        rpm=rpm,
    )


def test_token_bucket_paces_starts(fake_clock):
    starts = []
    bucket = ratelimit.TokenBucket(10, burst=1)

    async def drive():
        async def one():
            await bucket.acquire()
            starts.append(fake_clock.now())

        await asyncio.gather(*[one() for _ in range(50)])

    asyncio.run(drive())
    ordered = sorted(starts)
    assert ordered[-1] - ordered[0] == pytest.approx(4.9)
    assert _max_per_second(starts) <= 10


def test_token_bucket_validates_inputs():
    with pytest.raises(ValueError):
        ratelimit.TokenBucket(0)
    with pytest.raises(ValueError):
        ratelimit.TokenBucket(-5)
    with pytest.raises(ValueError):
        ratelimit.TokenBucket(10, burst=0.5)
    with pytest.raises(ValueError):
        ratelimit.TokenBucket.per_minute(0)


def test_runner_paces_requests_and_retries_count(fake_clock, tmp_path):
    qs = load_question_set("screen", 0)
    times = []
    # The first 5 requests get a zero-cost 429 and retry through before_send.
    ctx = _ctx(tmp_path, ["429"] * 5, fake_clock, times)
    out = asyncio.run(run_batch(ctx, items(40), qs))
    assert out["completed"] == 40 and out["failed"] == 0
    assert len(times) == 45  # 40 items + 5 retried attempts, all rate limited
    assert _max_per_second(times) <= 10


def test_cache_hits_never_acquire(fake_clock, tmp_path):
    qs = load_question_set("screen", 0)
    cache_path = tmp_path / "cache.sqlite"
    first = _ctx(tmp_path, [], fake_clock, [])
    first.cache_path = cache_path
    asyncio.run(run_batch(first, items(40), qs))

    times = []
    ctx = _ctx(tmp_path, [], fake_clock, times)
    ctx.run_id, ctx.run_dir = "r2", tmp_path / "r2"
    ctx.cache_path = cache_path
    calls = {"n": 0}
    original = ctx.limiter.acquire

    async def counting():
        calls["n"] += 1
        await original()

    ctx.limiter.acquire = counting
    out = asyncio.run(run_batch(ctx, items(40), qs))
    assert out["cache_hits"] == 40 and out["new_requests"] == 0
    assert calls["n"] == 0
    assert times == []


def test_rpm_none_leaves_limiter_off(tmp_path):
    ctx = _ctx(tmp_path, [], FakeClock(), [], rpm=None)
    assert ctx.limiter is None

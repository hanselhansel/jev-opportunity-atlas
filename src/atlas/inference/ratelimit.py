"""Requests-per-minute pacing for the runner's network sends.

`TokenBucket.acquire` waits until one token is available, so `rate_per_s`
bounds request starts in any window. The clock and sleep resolve the module
globals `_clock`/`_sleep` at construction, so tests can monkeypatch them;
production uses `time.monotonic` and `asyncio.sleep`.
"""

from __future__ import annotations

import asyncio
import time

_clock = time.monotonic


async def _sleep(delay: float) -> None:
    await asyncio.sleep(delay)


class TokenBucket:
    """Async token bucket; every `acquire` consumes exactly one token."""

    def __init__(
        self,
        rate_per_s: float,
        burst: float = 1.0,
        clock=None,
        sleep=None,
    ):
        if not rate_per_s > 0:
            raise ValueError(f"rate_per_s must be > 0, got {rate_per_s}")
        if not burst >= 1:
            raise ValueError(f"burst must be >= 1, got {burst}")
        self.rate = float(rate_per_s)
        self.burst = float(burst)
        self._clock = clock if clock is not None else _clock
        self._sleep = sleep if sleep is not None else _sleep
        self._tokens = self.burst
        self._last = self._clock()
        self._lock: asyncio.Lock | None = None
        self._lock_loop = None

    @classmethod
    def per_minute(cls, rpm: float, burst: float = 1.0) -> TokenBucket:
        return cls(rpm / 60.0, burst)

    def _get_lock(self) -> asyncio.Lock:
        # asyncio.run can drive several loops over one bucket; rebind per loop.
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def acquire(self) -> None:
        async with self._get_lock():
            while True:
                now = self._clock()
                self._tokens = min(
                    self.burst,
                    self._tokens + max(0.0, now - self._last) * self.rate,
                )
                self._last = max(self._last, now)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit_s = (1 - self._tokens) / self.rate
                await self._sleep(deficit_s)
                if self._clock() <= now:
                    # A sleep the clock could not see: the deficit was still
                    # waited out, so grant the token rather than spin.
                    self._tokens = 1.0
                    self._last = now + deficit_s

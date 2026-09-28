"""Budget guard: reserve estimated cost before each send, settle after.

`committed_usd = spent + unknown + reserved` can never pass the cap. Unknown
charges (timeouts, 5xx, null usage) settle at the worst case of
`max(worst_case_tokens_unknown, 2 * estimated_tokens)`.

`for_budget(name, ...)` rebuilds committed spend from every
`runs/*/ledger.jsonl` whose `run_manifest.json` names that budget, and holds an
exclusive `fcntl.flock` on `runs/.budget-<name>.lock` so two processes cannot
spend the same cap.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
from dataclasses import dataclass
from typing import Self

from atlas import paths
from atlas.inference.ledger import summarize


class BudgetExceeded(RuntimeError):
    pass


class BudgetLocked(RuntimeError):
    pass


@dataclass
class Reservation:
    """Open reservation returned by `reserve` and consumed by `settle`."""

    est_tokens: int
    cost_usd: float


class BudgetGuard:
    def __init__(
        self,
        cap_usd: float,
        usd_per_input_token: float,
        worst_case_tokens_unknown: int,
        name: str | None = None,
    ):
        self.cap_usd = cap_usd
        self.usd_per_input_token = usd_per_input_token
        self.worst_case_tokens_unknown = worst_case_tokens_unknown
        self.name = name
        self.spent_usd = 0.0
        self.unknown_usd = 0.0
        self.unknown_attempts = 0
        self.reserved_usd = 0.0
        self._alock: asyncio.Lock | None = None
        self._alock_loop = None
        self._lock_fd: int | None = None

    @property
    def committed_usd(self) -> float:
        return self.spent_usd + self.unknown_usd + self.reserved_usd

    def _lock(self) -> asyncio.Lock:
        # asyncio.run can drive several loops over one guard; rebind per loop.
        loop = asyncio.get_running_loop()
        if self._alock is None or self._alock_loop is not loop:
            self._alock = asyncio.Lock()
            self._alock_loop = loop
        return self._alock

    async def reserve(self, est_tokens: int) -> Reservation:
        async with self._lock():
            cost = est_tokens * self.usd_per_input_token
            if self.committed_usd + cost > self.cap_usd:
                raise BudgetExceeded(
                    f"budget {self.name or '<unnamed>'}: "
                    f"{self.committed_usd + cost:.6f} > cap {self.cap_usd:.6f}"
                )
            self.reserved_usd += cost
            return Reservation(est_tokens=est_tokens, cost_usd=cost)

    async def settle(
        self, handle: Reservation, actual_tokens: int | None, known: bool
    ) -> None:
        async with self._lock():
            self.reserved_usd -= handle.cost_usd
            if known:
                self.spent_usd += (actual_tokens or 0) * self.usd_per_input_token
            else:
                self.unknown_attempts += 1
                self.unknown_usd += (
                    max(self.worst_case_tokens_unknown, 2 * handle.est_tokens)
                    * self.usd_per_input_token
                )

    @classmethod
    def from_summary(
        cls,
        summary: dict,
        cap_usd: float,
        usd_per_input_token: float,
        worst_case_tokens_unknown: int,
        name: str | None = None,
    ) -> BudgetGuard:
        g = cls(cap_usd, usd_per_input_token, worst_case_tokens_unknown, name=name)
        g.spent_usd = summary.get("calculated_usd") or 0.0
        g.unknown_attempts = summary.get("unknown_attempts") or 0
        g.unknown_usd = (
            g.unknown_attempts * worst_case_tokens_unknown * usd_per_input_token
        )
        return g

    @classmethod
    def for_budget(
        cls,
        name: str,
        cap_usd: float,
        usd_per_input_token: float,
        worst_case_tokens_unknown: int,
    ) -> BudgetGuard:
        paths.RUNS.mkdir(parents=True, exist_ok=True)
        lock_path = paths.RUNS / f".budget-{name}.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            raise BudgetLocked(
                f"budget {name!r} is held by another run ({lock_path})"
            ) from None
        calculated = 0.0
        unknown = 0
        for manifest in sorted(paths.RUNS.glob("*/run_manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("budget") != name:
                continue
            ledger = manifest.parent / "ledger.jsonl"
            if not ledger.exists():
                continue
            s = summarize(ledger)
            calculated += s["calculated_usd"]
            unknown += s["unknown_attempts"]
        guard = cls.from_summary(
            {"calculated_usd": calculated, "unknown_attempts": unknown},
            cap_usd,
            usd_per_input_token,
            worst_case_tokens_unknown,
            name=name,
        )
        guard._lock_fd = lock_fd
        return guard

    def close(self) -> None:
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

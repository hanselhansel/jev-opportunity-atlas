"""Budget guard: reserve estimated cost before each send, settle after.

`committed_usd = spent + unknown + reserved` can never pass the cap. Unknown
charges (timeouts, 5xx, null usage) settle at the worst case of
`max(worst_case_tokens_unknown, 2 * estimated_tokens)`.

Two caps apply: the per-name cap (`committed_usd <= cap_usd`) and the account
total (`account_committed_usd <= account_total`), which sums committed spend
across every budget name. `for_budget` takes two flock locks,
`runs/.budget-account.lock` then `runs/.budget-<name>.lock`, so only one paid
run can be in flight at a time and no pair of runs can split a cap.

Limitation: unknown attempts rebuilt from disk settle at the flat
`worst_case_tokens_per_unknown_attempt`, not the live
`max(worst_case, 2 * est_tokens)` rule used for attempts settled in-process.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import tomllib
from dataclasses import dataclass
from typing import Self

from atlas import paths
from atlas.inference.ledger import read_rows, summarize, unresolved_pending


class BudgetExceeded(RuntimeError):
    pass


class BudgetLocked(RuntimeError):
    pass


_DEFAULT_RESUME = (
    "rerun the same command with the same --run after the cap in "
    "configs/budgets.toml allows it; check headroom with `atlas jev budget`"
)


def load_budgets() -> dict:
    return tomllib.loads(
        (paths.CONFIGS / "budgets.toml").read_text(encoding="utf-8")
    )


def budget_names(cfg: dict) -> list[str]:
    """Configured budget names: everything except account_total and worst_case*."""
    return [
        k
        for k in cfg
        if k != "account_total" and not k.startswith("worst_case")
    ]


def scan_runs() -> dict[str, dict]:
    """One pass over every run dir: per-budget-name calculated spend, unknown
    and pending attempts. Unreadable manifests raise rather than skip (a skip
    would silently undercount spend)."""
    out: dict[str, dict] = {}
    for manifest in sorted(paths.RUNS.glob("*/run_manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"unreadable run manifest {manifest}: {exc}"
            ) from exc
        ledger = manifest.parent / "ledger.jsonl"
        if not ledger.exists():
            continue
        name = data.get("budget") or "<none>"
        s = summarize(ledger)
        entry = out.setdefault(
            name,
            {
                "calculated_usd": 0.0,
                "unknown_attempts": 0,
                "pending_attempts": 0,
                "runs": 0,
            },
        )
        entry["calculated_usd"] += s["calculated_usd"]
        entry["unknown_attempts"] += s["unknown_attempts"]
        entry["pending_attempts"] += len(unresolved_pending(read_rows(ledger)))
        entry["runs"] += 1
    return out


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
        account_total: float | None = None,
        other_committed_usd: float = 0.0,
    ):
        self.cap_usd = cap_usd
        self.usd_per_input_token = usd_per_input_token
        self.worst_case_tokens_unknown = worst_case_tokens_unknown
        self.name = name
        self.account_total = account_total
        self.other_committed_usd = other_committed_usd
        self.resume_command: str | None = None
        self.spent_usd = 0.0
        self.unknown_usd = 0.0
        self.unknown_attempts = 0
        self.reserved_usd = 0.0
        self._alock: asyncio.Lock | None = None
        self._alock_loop = None
        self._lock_fds: list[int] = []

    @property
    def committed_usd(self) -> float:
        return self.spent_usd + self.unknown_usd + self.reserved_usd

    @property
    def account_committed_usd(self) -> float:
        return self.other_committed_usd + self.committed_usd

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
            if self.committed_usd + cost > self.cap_usd or (
                self.account_total is not None
                and self.account_committed_usd + cost > self.account_total
            ):
                total = (
                    f"{self.account_total:.6f}"
                    if self.account_total is not None
                    else "none"
                )
                raise BudgetExceeded(
                    f"budget {self.name or '<unnamed>'!r}: "
                    f"name cap {self.cap_usd:.6f}, "
                    f"name committed {self.committed_usd:.6f}, "
                    f"account total {total}, "
                    f"account committed {self.account_committed_usd:.6f}, "
                    f"request {cost:.6f} would pass a cap. "
                    f"Resume: {self.resume_command or _DEFAULT_RESUME}"
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
        account_total: float | None = None,
    ) -> BudgetGuard:
        if account_total is None:
            cfg = load_budgets()
            if "account_total" not in cfg:
                raise RuntimeError(
                    f"account_total missing in {paths.CONFIGS / 'budgets.toml'}"
                )
            account_total = cfg["account_total"]
        paths.RUNS.mkdir(parents=True, exist_ok=True)
        lock_fds: list[int] = []
        try:
            for lock_path in (
                paths.RUNS / ".budget-account.lock",
                paths.RUNS / f".budget-{name}.lock",
            ):
                fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    raise BudgetLocked(
                        f"budget {name!r} is held by another run ({lock_path})"
                    ) from None
                lock_fds.append(fd)
            scan = scan_runs()
        except BaseException:
            for fd in lock_fds:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            raise
        mine = scan.get(name) or {
            "calculated_usd": 0.0,
            "unknown_attempts": 0,
        }
        others = sum(
            s["calculated_usd"]
            + s["unknown_attempts"]
            * worst_case_tokens_unknown
            * usd_per_input_token
            for n, s in scan.items()
            if n != name
        )
        guard = cls.from_summary(
            mine,
            cap_usd,
            usd_per_input_token,
            worst_case_tokens_unknown,
            name=name,
        )
        guard.account_total = account_total
        guard.other_committed_usd = others
        guard._lock_fds = lock_fds
        return guard

    def close(self) -> None:
        fds, self._lock_fds = self._lock_fds, []
        for fd in fds:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

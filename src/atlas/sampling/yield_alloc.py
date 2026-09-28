"""Yield-aware allocation: maximize expected firsthand problems per token.

The per-stratum floor keeps every eligible comment's inclusion probability
nonzero and bounds the design weights (the largest possible weight is
1 / floor_rate). The allocation depends only on stratum sizes and on pilot
inputs (p_h, c_h) fixed before the draw, never on main-run answers, so the
resulting inclusion probabilities stay valid for unbiased estimation.
"""

from __future__ import annotations

import math


def allocate_by_yield(
    N: dict[str, int],
    p: dict[str, float],
    c: dict[str, float],
    budget_tokens: float,
    floor_rate: float,
    min_n: int = 30,
) -> dict[str, int]:
    """Floor every stratum, then spend the rest on the highest p_h / c_h.

    base_h = min(N_h, max(min_n, ceil(floor_rate * N_h))); if the floors alone
    exceed budget_tokens this raises ValueError. Remaining tokens go greedily
    to strata by descending p_h / c_h (ties broken by label), filling each
    stratum to N_h before moving on; a partially filled stratum leaves the
    leftovers to cheaper strata. Returns integer allocations, keys sorted.
    """
    if not 0 < floor_rate <= 1:
        raise ValueError(f"floor_rate must be in (0, 1], got {floor_rate}")
    if set(N) != set(p) or set(N) != set(c):
        raise ValueError("N, p, and c must have the same stratum keys")
    for h, n_h in N.items():
        if not 0 <= p[h] <= 1:
            raise ValueError(f"p[{h}]={p[h]} outside [0, 1]")
        if not c[h] > 0:
            raise ValueError(f"c[{h}]={c[h]} must be > 0")
        if n_h < 0:
            raise ValueError(f"N[{h}]={n_h} must be >= 0")

    base = {
        h: (
            min(N[h], max(min_n, math.ceil(round(floor_rate * N[h], 9))))
            if N[h] > 0
            else 0
        )
        for h in N
    }
    needed = sum(base[h] * c[h] for h in N)
    if needed > budget_tokens:
        raise ValueError(
            f"floor allocation needs {needed:.0f} tokens, "
            f"budget is {budget_tokens:.0f}"
        )
    alloc = dict(base)
    remaining = budget_tokens - needed
    for h in sorted(N, key=lambda h: (-p[h] / c[h], h)):
        add = min(N[h] - alloc[h], math.floor(remaining / c[h]))
        if add > 0:
            alloc[h] += add
            remaining -= add * c[h]
    return {h: int(alloc[h]) for h in sorted(alloc)}


def expected_positives(alloc: dict[str, int], p: dict[str, float]) -> float:
    """Expected firsthand problems found: sum_h alloc_h * p_h."""
    return sum(alloc[h] * p[h] for h in alloc)


def expected_tokens(alloc: dict[str, int], c: dict[str, float]) -> float:
    """Expected screen tokens spent: sum_h alloc_h * c_h."""
    return sum(alloc[h] * c[h] for h in alloc)


def largest_weight(alloc: dict[str, int], N: dict[str, int]) -> float:
    """Largest design weight N_h / n_h over strata that received units."""
    return max(N[h] / alloc[h] for h in alloc if alloc[h] > 0)

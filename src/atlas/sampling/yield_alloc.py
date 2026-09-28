"""Yield-aware allocation: maximize expected firsthand problems per token.

The per-stratum floor keeps every eligible comment's inclusion probability
nonzero and bounds the design weights (the largest possible weight is
1 / floor_rate). The allocation depends only on stratum sizes and on pilot
inputs (p_h, c_h) fixed before the draw, never on main-run answers, so the
resulting inclusion probabilities stay valid for unbiased estimation.
"""

from __future__ import annotations

import json
import math
import tomllib

import pyarrow as pa


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


def price_per_token() -> tuple[float, str]:
    """(USD per input token, price version) from the last [[price]] entry."""
    from atlas import paths

    cfg = tomllib.loads((paths.CONFIGS / "prices.toml").read_text())
    entry = cfg["price"][-1]
    return entry["input_usd_per_million"] / 1e6, entry["version"]


def usd_to_tokens(budget_usd: float) -> int:
    """Convert a USD budget into whole input tokens at the current price."""
    usd_per_token, _ = price_per_token()
    return math.floor(budget_usd / usd_per_token)


def _levels(h: str) -> list[str]:
    parts = h.split("|")
    return [h, "|".join(parts[:2]), parts[0], "*"]


def _at_level(observed: dict[int, object], stratum_of: dict[int, str], key: str):
    return {
        cid: v
        for cid, v in observed.items()
        if (s := stratum_of.get(cid)) is not None
        and (key == "*" or s == key or s.startswith(key + "|"))
    }


def _pick_level(observed, stratum_of, h, min_n):
    """First level key with >= min_n observations; "*" always stops the walk."""
    for key in _levels(h):
        obs = _at_level(observed, stratum_of, key)
        if key == "*" or len(obs) >= min_n:
            return key, obs
    return "*", {}  # unreachable: _levels always ends with "*"


def _pilot_observations(frame: pa.Table, run_id: str, cfg: dict):
    """comment_id -> firsthand flag and -> summed screen input tokens."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from atlas import paths

    firsthand: dict[int, bool] = {}
    parts = sorted((paths.run_dir(run_id) / "answers").glob("part-*.parquet"))
    if parts:
        answers = pq.read_table(parts)
        answers = answers.filter(
            pc.and_(
                pc.equal(
                    answers.column("question_set"), cfg["screen_question_set"]
                ),
                pc.equal(answers.column("question_id"), cfg["firsthand_question"]),
            )
        )
        sums: dict[int, float] = {}
        counts: dict[int, int] = {}
        for cid, noul in zip(
            answers.column("comment_id").to_pylist(),
            answers.column("noul").to_pylist(),
        ):
            if cid is None or noul is None:
                continue
            sums[cid] = sums.get(cid, 0.0) + noul
            counts[cid] = counts.get(cid, 0) + 1
        threshold = cfg["firsthand_threshold"]
        firsthand = {
            cid: sums[cid] / counts[cid] >= threshold for cid in sums
        }

    tokens: dict[int, float] = {}
    ledger = paths.ledger_path(run_id)
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                row.get("question_set") == cfg["screen_question_set"]
                and row.get("cost_class") == "calculated"
                and row.get("input_tokens") is not None
                and row.get("comment_id") is not None
            ):
                cid = row["comment_id"]
                tokens[cid] = tokens.get(cid, 0.0) + row["input_tokens"]

    cids = frame.column("comment_id").to_pylist()
    stratum_of = dict(zip(cids, frame.column("stratum").to_pylist()))
    return firsthand, tokens, stratum_of


def pilot_inputs(
    frame: pa.Table, run_id: str, cfg: dict
) -> tuple[dict[str, float], dict[str, float], dict[str, dict]]:
    """Per-stratum firsthand rate p_h and mean screen tokens c_h from a pilot.

    Each stratum falls back to a coarser level ("pain|L2|H1|ask" -> "pain|L2"
    -> "pain" -> "*") until at least cfg["min_pilot_n"] pilot comments back the
    estimate; "*" uses whatever pilot data exists and only fails when the run
    has none at all. Pilot comments that are not in the frame are dropped.
    """
    firsthand, tokens, stratum_of = _pilot_observations(frame, run_id, cfg)
    min_n = cfg["min_pilot_n"]
    p: dict[str, float] = {}
    c: dict[str, float] = {}
    levels: dict[str, dict] = {}
    for h in sorted(set(stratum_of.values())):
        key_p, obs_p = _pick_level(firsthand, stratum_of, h, min_n)
        if not obs_p:
            raise ValueError(f"run {run_id}: no firsthand answers usable")
        key_c, obs_c = _pick_level(tokens, stratum_of, h, min_n)
        if not obs_c:
            raise ValueError(f"run {run_id}: no screen token rows usable")
        p[h] = sum(obs_p.values()) / len(obs_p)
        c[h] = sum(obs_c.values()) / len(obs_c)
        levels[h] = {"p": key_p, "c": key_c}
    return p, c, levels

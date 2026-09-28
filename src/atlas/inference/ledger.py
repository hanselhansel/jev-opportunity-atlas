"""Append-only JSONL attempt ledger and its summaries.

One ledger row per network attempt (cost_class calculated | unknown | pending)
and one per cache replay (attempt=0, cost_class replay). A `pending` row written
before send is superseded by the final attempt row for the same
(run_id, logical_call_id, attempt); on restart an unresolved pending row counts
as an unknown charge, never silently dropped.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Self

import numpy as np

from atlas import contracts

SYNC_EVERY = 50


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self._rows = 0
        self._closed = False

    def append(self, row: dict, sync: bool = False) -> None:
        unknown = set(row) - set(contracts.LEDGER_FIELDS)
        if unknown:
            raise KeyError(f"unknown ledger fields: {sorted(unknown)}")
        out = {k: row.get(k) for k in contracts.LEDGER_FIELDS}
        self._fh.write(json.dumps(out, ensure_ascii=False) + "\n")
        self._rows += 1
        self._fh.flush()
        if sync or self._rows % SYNC_EVERY == 0:
            os.fsync(self._fh.fileno())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


def read_rows(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def unresolved_pending(rows: list[dict]) -> list[dict]:
    """Pending rows with no non-pending row for the same
    (run_id, logical_call_id, attempt): sends that crashed mid-flight."""
    finals = {
        (r.get("run_id"), r.get("logical_call_id"), r.get("attempt"))
        for r in rows
        if r.get("cost_class") != "pending"
    }
    return [
        r
        for r in rows
        if r.get("cost_class") == "pending"
        and (r.get("run_id"), r.get("logical_call_id"), r.get("attempt")) not in finals
    ]


def _timed_ms(rows: list[dict]) -> list[float]:
    return [
        r["request_ms"]
        for r in rows
        if r.get("http_status") is not None and r.get("request_ms") is not None
    ]


def _percentiles(rows: list[dict]) -> tuple[float | None, float | None]:
    vals = _timed_ms(rows)
    if not vals:
        return None, None
    return float(np.percentile(vals, 50)), float(np.percentile(vals, 95))


def _set_stats(rows: list[dict]) -> dict:
    known = [r["input_tokens"] for r in rows if r.get("input_tokens") is not None]
    p50, p95 = _percentiles(rows)
    return {
        "calls": len({r.get("logical_call_id") for r in rows}),
        "input_tokens": sum(known),
        "mean_tokens": (sum(known) / len(known)) if known else None,
        "p50_ms": p50,
        "p95_ms": p95,
        "calculated_usd": sum(
            r["cost_usd"]
            for r in rows
            if r.get("cost_class") == "calculated" and r.get("cost_usd") is not None
        ),
        "unknown_attempts": sum(1 for r in rows if r.get("cost_class") in ("unknown", "pending")),
    }


def summarize(path, by: str | None = None) -> dict:
    rows = read_rows(path)
    pending = unresolved_pending(rows)
    network = [
        r for r in rows if r.get("cost_class") not in ("pending", "replay")
    ] + pending
    replays = [r for r in rows if r.get("cost_class") == "replay"]

    per_id = Counter(r.get("logical_call_id") for r in network)
    p50, p95 = _percentiles(network)
    summary = {
        "attempts": len(network),
        "logical_calls": len({r.get("logical_call_id") for r in network + replays}),
        "retried_calls": sum(1 for n in per_id.values() if n > 1),
        "calculated_usd": sum(
            r["cost_usd"]
            for r in rows
            if r.get("cost_class") == "calculated" and r.get("cost_usd") is not None
        ),
        "unknown_attempts": sum(
            1 for r in rows if r.get("cost_class") == "unknown"
        )
        + len(pending),
        "replays": len(replays),
        "input_tokens": sum(
            r["input_tokens"] for r in network if r.get("input_tokens") is not None
        ),
        "p50_request_ms": p50,
        "p95_request_ms": p95,
        "by_status": dict(
            Counter(str(r.get("http_status") or "none") for r in network)
        ),
    }
    if by == "question_set":
        groups: dict = {}
        for r in network:
            groups.setdefault(r.get("question_set"), []).append(r)
        summary["question_sets"] = {
            label: _set_stats(rs) for label, rs in groups.items()
        }
    elif by is not None:
        raise ValueError(f"unknown summarize grouping: {by!r}")
    return summary

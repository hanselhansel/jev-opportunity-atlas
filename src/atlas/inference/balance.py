"""Credit balance log: record the TypeSafe console balance, then reconcile.

`record_balance` appends one line to runs/balance.jsonl. `reconcile` pairs
consecutive records and compares the provider delta against ledger spend in
each (start, end] interval: calculated rows at cost_usd, unknown and
unresolved-pending attempts at the flat worst case.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from atlas import paths
from atlas.inference.ledger import read_rows, unresolved_pending

_EPSILON = 0.01  # console precision


def balance_path():
    return paths.RUNS / "balance.jsonl"


def record_balance(usd: float, note: str = "", at: str | None = None) -> dict:
    record = {
        "at": at or datetime.now(UTC).isoformat(),
        "usd": float(usd),
        "note": note,
    }
    paths.RUNS.mkdir(parents=True, exist_ok=True)
    with balance_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def _records() -> list[dict]:
    path = balance_path()
    if not path.exists():
        return []
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted(rows, key=lambda r: datetime.fromisoformat(r["at"]))


def _row_time(row: dict):
    when = row.get("ended_at") or row.get("started_at")
    return datetime.fromisoformat(when) if when else None


def _interval_spend(start: datetime, end: datetime) -> tuple[float, int]:
    calculated = 0.0
    unknown = 0
    for ledger in sorted(paths.RUNS.glob("*/ledger.jsonl")):
        rows = read_rows(ledger)
        pending = {
            (r.get("run_id"), r.get("logical_call_id"), r.get("attempt"))
            for r in unresolved_pending(rows)
        }
        for row in rows:
            t = _row_time(row)
            if t is None or not (start < t <= end):
                continue
            if row.get("cost_class") == "calculated":
                calculated += row.get("cost_usd") or 0.0
            elif row.get("cost_class") == "unknown" or row.get("cost_class") == "pending" and (
                row.get("run_id"),
                row.get("logical_call_id"),
                row.get("attempt"),
            ) in pending:
                unknown += 1
    return calculated, unknown


def reconcile(
    usd_per_input_token: float | None = None,
    worst_case_tokens: int | None = None,
) -> list[dict]:
    if usd_per_input_token is None:
        from atlas.inference.cli import MODEL  # lazy: avoid the import cycle
        from atlas.inference.estimate import input_price

        usd_per_input_token = input_price(MODEL)
    if worst_case_tokens is None:
        from atlas.inference.budget import load_budgets

        worst_case_tokens = load_budgets()["worst_case_tokens_per_unknown_attempt"]
    out = []
    for a, b in zip(_records(), _records()[1:]):
        start, end = datetime.fromisoformat(a["at"]), datetime.fromisoformat(b["at"])
        calculated, unknown = _interval_spend(start, end)
        provider_delta = a["usd"] - b["usd"]
        difference = provider_delta - calculated
        unknown_worst_usd = unknown * worst_case_tokens * usd_per_input_token
        if abs(difference) <= _EPSILON and unknown == 0:
            status = "reconciled"
        elif -_EPSILON <= difference <= unknown_worst_usd + _EPSILON:
            status = "explained_by_unknown"
        else:
            status = "unexplained"
        out.append(
            {
                "start": a["at"],
                "end": b["at"],
                "provider_delta": provider_delta,
                "calculated": calculated,
                "unknown_attempts": unknown,
                "unknown_worst_usd": unknown_worst_usd,
                "difference": difference,
                "status": status,
            }
        )
    return out

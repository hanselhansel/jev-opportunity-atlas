import asyncio
import json
import subprocess
import sys

import pytest

from atlas import contracts as c
from atlas import paths
from atlas.inference.budget import BudgetExceeded, BudgetGuard, BudgetLocked
from atlas.inference.ledger import Ledger

PRICE = 0.042e-6


def ledger_row(**over):
    base = {k: None for k in c.LEDGER_FIELDS}
    base.update(
        run_id="r1",
        logical_call_id="L1",
        attempt=1,
        cost_class="calculated",
        cost_usd=0.25,
        input_tokens=300,
    )
    base.update(over)
    return base


def test_reserve_settle_and_stop():
    g = BudgetGuard(cap_usd=0.001, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000)
    r = asyncio.run(g.reserve(est_tokens=10_000))           # 0.00042
    asyncio.run(g.settle(r, actual_tokens=9_000, known=True))
    assert g.spent_usd == pytest.approx(9_000 * PRICE) and g.reserved_usd == 0
    with pytest.raises(BudgetExceeded):
        asyncio.run(g.reserve(est_tokens=20_000))           # would pass the cap


def test_unknown_charges_count_at_worst_case():
    g = BudgetGuard(cap_usd=1.0, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000)
    r = asyncio.run(g.reserve(est_tokens=500))
    asyncio.run(g.settle(r, actual_tokens=None, known=False))
    assert g.unknown_attempts == 1 and g.committed_usd == pytest.approx(8000 * PRICE)


def test_retry_worst_case_uses_twice_estimate():
    g = BudgetGuard(cap_usd=1.0, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000)
    r = asyncio.run(g.reserve(est_tokens=10_000))
    asyncio.run(g.settle(r, actual_tokens=None, known=False))
    assert g.unknown_attempts == 1
    assert g.unknown_usd == pytest.approx(20_000 * PRICE)


def test_resume_from_ledger_summary():
    g = BudgetGuard.from_summary({"calculated_usd": 0.5, "unknown_attempts": 2}, cap_usd=1.0,
                                 usd_per_input_token=PRICE, worst_case_tokens_unknown=8000)
    assert g.committed_usd == pytest.approx(0.5 + 2 * 8000 * PRICE)


def _run_dir_with_spend(runs, name, budget, cost_usd):
    run_dir = runs / name
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": name, "budget": budget})
    )
    led = Ledger(run_dir / "ledger.jsonl")
    led.append(ledger_row(run_id=name, cost_usd=cost_usd))
    led.close()


def test_guard_cumulative_across_runs(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _run_dir_with_spend(runs, "A", "pilot", 0.25)
    _run_dir_with_spend(runs, "B", "main", 9.99)  # different budget: ignored
    g = BudgetGuard.for_budget(
        "pilot", cap_usd=1.0, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000
    )
    try:
        assert g.committed_usd == pytest.approx(0.25)
        with pytest.raises(BudgetLocked):
            BudgetGuard.for_budget(
                "pilot",
                cap_usd=1.0,
                usd_per_input_token=PRICE,
                worst_case_tokens_unknown=8000,
            )
    finally:
        g.close()


def test_second_process_cannot_take_lock(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    g = BudgetGuard.for_budget(
        "pilot", cap_usd=1.0, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000
    )
    lock_path = runs / ".budget-pilot.lock"
    script = (
        "import fcntl, sys\n"
        f"fh = open({str(lock_path)!r})\n"
        "try:\n"
        "    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n"
    )
    try:
        assert subprocess.run([sys.executable, "-c", script], check=False).returncode == 1
    finally:
        g.close()
    assert subprocess.run([sys.executable, "-c", script], check=False).returncode == 0

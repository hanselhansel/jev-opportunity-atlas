import asyncio
import json
import subprocess
import sys

import pytest

from atlas import cli, paths
from atlas import contracts as c
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


def _run_dir_with_rows(runs, name, budget, rows):
    run_dir = runs / name
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": name, "budget": budget})
    )
    led = Ledger(run_dir / "ledger.jsonl")
    for r in rows:
        led.append(r)
    led.close()


def _guard(name, account_total=25.0, cap_usd=6.5):
    return BudgetGuard.for_budget(
        name,
        cap_usd=cap_usd,
        usd_per_input_token=PRICE,
        worst_case_tokens_unknown=8000,
        account_total=account_total,
    )


def test_account_cap_counts_other_budgets(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _run_dir_with_rows(
        runs, "A", "pilot", [ledger_row(run_id="A", cost_usd=0.0009)]
    )
    g = _guard("screen", account_total=0.001)
    try:
        assert g.account_total == 0.001
        assert g.other_committed_usd == pytest.approx(0.0009)
        assert g.account_committed_usd == pytest.approx(0.0009)
        r = asyncio.run(g.reserve(est_tokens=1000))  # 0.000042 fits under 0.001
        assert r.cost_usd == pytest.approx(0.000042)
        with pytest.raises(BudgetExceeded):
            asyncio.run(g.reserve(est_tokens=2000))  # would pass the account cap
    finally:
        g.close()


def test_unknown_and_pending_from_other_budgets_count(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _run_dir_with_rows(
        runs,
        "A",
        "pilot",
        [
            ledger_row(
                run_id="A",
                logical_call_id="L1",
                cost_class="unknown",
                cost_usd=None,
                input_tokens=None,
            ),
            ledger_row(
                run_id="A",
                logical_call_id="L2",
                cost_class="pending",
                cost_usd=None,
                input_tokens=None,
                ended_at=None,
            ),
        ],
    )
    g = _guard("screen")
    try:
        # unknown + unresolved pending, at the flat worst case
        assert g.other_committed_usd == pytest.approx(2 * 8000 * PRICE)
        assert g.account_committed_usd == pytest.approx(2 * 8000 * PRICE)
    finally:
        g.close()


def test_second_budget_blocked_by_account_lock(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    g = _guard("pilot")
    try:
        with pytest.raises(BudgetLocked, match="budget-account"):
            _guard("screen")
    finally:
        g.close()


def test_account_lock_held_for_other_process(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    g = _guard("pilot")
    lock_path = runs / ".budget-account.lock"
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


def test_failed_scan_releases_both_locks(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    bad = runs / "bad-run"
    bad.mkdir(parents=True)
    (bad / "run_manifest.json").write_text("{not json")
    with pytest.raises(RuntimeError, match="run_manifest"):
        _guard("pilot")
    # after the failed scan neither lock is held
    (bad / "run_manifest.json").write_text(json.dumps({"budget": "other"}))
    g = _guard("pilot")
    g.close()
    g2 = _guard("screen")
    g2.close()


def test_error_message_lists_caps_and_resume(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _run_dir_with_rows(
        runs, "A", "pilot", [ledger_row(run_id="A", cost_usd=0.0009)]
    )
    g = _guard("screen", account_total=0.001)
    try:
        with pytest.raises(BudgetExceeded) as exc:
            asyncio.run(g.reserve(est_tokens=3000))
    finally:
        g.close()
    msg = str(exc.value)
    for part in (
        "name cap",
        "name committed",
        "account total",
        "account committed",
        "Resume",
    ):
        assert part in msg


def test_account_total_read_from_config(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "budgets.toml").write_text(
        "account_total = 0.5\npilot = 0.1\n", encoding="utf-8"
    )
    monkeypatch.setattr(paths, "RUNS", runs)
    monkeypatch.setattr(paths, "CONFIGS", configs)
    g = BudgetGuard.for_budget(
        "pilot",
        cap_usd=1.0,
        usd_per_input_token=PRICE,
        worst_case_tokens_unknown=8000,
    )
    try:
        assert g.account_total == 0.5
    finally:
        g.close()


def test_jev_budget_read_only(tmp_path, monkeypatch, capsys):
    runs = tmp_path / "runs"
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "budgets.toml").write_text(
        "account_total = 0.001\n"
        "pilot = 0.0005\n"
        "screen = 6.5\n"
        "worst_case_tokens_per_unknown_attempt = 8000\n",
        encoding="utf-8",
    )
    (configs / "prices.toml").write_text(
        '[[price]]\nversion = "v"\nmodel = "jev-1.13.0"\n'
        "input_usd_per_million = 0.042\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "RUNS", runs)
    monkeypatch.setattr(paths, "CONFIGS", configs)
    _run_dir_with_rows(
        runs, "A", "pilot", [ledger_row(run_id="A", cost_usd=0.0002)]
    )
    _run_dir_with_rows(
        runs, "B", "mystery", [ledger_row(run_id="B", cost_usd=0.0001)]
    )
    # read-only: must work while a run holds both locks
    g = _guard("screen", account_total=0.001)
    try:
        args = cli.build_parser().parse_args(["jev", "budget"])
        args.func(args)
    finally:
        g.close()
    out = json.loads(capsys.readouterr().out)
    assert out["names"]["pilot"]["cap_usd"] == 0.0005
    assert out["names"]["pilot"]["calculated_usd"] == pytest.approx(0.0002)
    assert out["names"]["pilot"]["committed_usd"] == pytest.approx(0.0002)
    assert out["names"]["pilot"]["remaining_usd"] == pytest.approx(0.0003)
    assert out["names"]["screen"]["calculated_usd"] == 0.0
    assert out["names"]["mystery"]["cap_usd"] is None
    assert out["names"]["mystery"]["remaining_usd"] is None
    assert out["account"]["total_usd"] == 0.001
    assert out["account"]["committed_usd"] == pytest.approx(0.0003)
    assert out["account"]["remaining_usd"] == pytest.approx(0.0007)

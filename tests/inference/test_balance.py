import json

import pytest

from atlas import contracts as c
from atlas import paths
from atlas.inference.balance import balance_path, reconcile, record_balance
from atlas.inference.ledger import Ledger

PRICE = 0.042e-6
T0 = "2026-09-29T00:00:00+00:00"
T1 = "2026-09-29T01:00:00+00:00"


def _row(run_id, lid, **over):
    base = {k: None for k in c.LEDGER_FIELDS}
    base.update(run_id=run_id, logical_call_id=lid, attempt=1)
    base.update(over)
    return base


def _run_with_rows(runs, name, rows):
    run_dir = runs / name
    run_dir.mkdir(parents=True)
    led = Ledger(run_dir / "ledger.jsonl")
    for r in rows:
        led.append(r)
    led.close()


def test_record_balance_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    rec = record_balance(25.0, note="initial", at=T0)
    assert rec == {"at": T0, "usd": 25.0, "note": "initial"}
    line = json.loads(balance_path().read_text(encoding="utf-8").splitlines()[0])
    assert line == rec
    record_balance(24.5, at=T1)
    assert len(balance_path().read_text(encoding="utf-8").splitlines()) == 2


def test_reconcile_reconciled_interval(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _run_with_rows(
        runs,
        "A",
        [
            _row(
                "A",
                "L1",
                cost_class="calculated",
                cost_usd=0.00126,
                input_tokens=30000,
                started_at="2026-09-29T00:30:00+00:00",
                ended_at="2026-09-29T00:30:01+00:00",
            ),
            # outside the interval: ignored
            _row(
                "A",
                "L2",
                cost_class="calculated",
                cost_usd=5.0,
                started_at="2026-09-28T23:00:00+00:00",
                ended_at="2026-09-28T23:00:01+00:00",
            ),
        ],
    )
    record_balance(25.0, at=T0)
    record_balance(24.99874, at=T1)
    out = reconcile(usd_per_input_token=PRICE, worst_case_tokens=8000)
    assert len(out) == 1
    iv = out[0]
    assert iv["start"] == T0 and iv["end"] == T1
    assert iv["provider_delta"] == pytest.approx(0.00126)
    assert iv["calculated"] == pytest.approx(0.00126)
    assert iv["unknown_attempts"] == 0
    assert iv["difference"] == pytest.approx(0.0)
    assert iv["status"] == "reconciled"


def test_reconcile_explained_by_unknown_and_pending(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _run_with_rows(
        runs,
        "A",
        [
            _row(
                "A",
                "L1",
                cost_class="unknown",
                cost_usd=None,
                started_at="2026-09-29T00:10:00+00:00",
                ended_at="2026-09-29T00:10:05+00:00",
            ),
            # unresolved pending counts by started_at (no ended_at)
            _row(
                "A",
                "L2",
                cost_class="pending",
                cost_usd=None,
                started_at="2026-09-29T00:20:00+00:00",
                ended_at=None,
            ),
        ],
    )
    record_balance(25.0, at=T0)
    record_balance(24.995, at=T1)
    out = reconcile(usd_per_input_token=PRICE, worst_case_tokens=8000)
    iv = out[0]
    assert iv["unknown_attempts"] == 2
    assert iv["unknown_worst_usd"] == pytest.approx(2 * 8000 * PRICE)
    assert iv["provider_delta"] == pytest.approx(0.005)
    assert iv["status"] == "explained_by_unknown"


def test_reconcile_unexplained(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    record_balance(25.0, at=T0)
    record_balance(20.0, at=T1)
    out = reconcile(usd_per_input_token=PRICE, worst_case_tokens=8000)
    iv = out[0]
    assert iv["provider_delta"] == pytest.approx(5.0)
    assert iv["calculated"] == 0.0
    assert iv["status"] == "unexplained"

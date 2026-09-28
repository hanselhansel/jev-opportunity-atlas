import json

import pytest

from atlas import contracts as c
from atlas.inference.ledger import Ledger, summarize


def row(**over):
    base = {k: None for k in c.LEDGER_FIELDS}
    base.update(
        run_id="r1",
        logical_call_id="L1",
        attempt=1,
        cost_class="calculated",
        cost_usd=0.0000126,
        input_tokens=300,
        output_tokens=20,
        cache="miss",
    )
    base.update(over)
    return base


def test_rows_have_exact_fields_in_order(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(row())
    led.close()
    line = (tmp_path / "ledger.jsonl").read_text().splitlines()[0]
    assert list(json.loads(line)) == list(c.LEDGER_FIELDS)


def test_missing_fields_fill_none(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append({"run_id": "r1", "logical_call_id": "L9", "attempt": 2})
    led.close()
    written = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[0])
    assert written["run_id"] == "r1" and written["cost_class"] is None
    assert list(written) == list(c.LEDGER_FIELDS)


def test_unknown_field_is_rejected(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    try:
        led.append({**row(), "authorization": "x"})
    except KeyError:
        return
    raise AssertionError("extra field accepted")


def test_summary_separates_cost_classes(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(row())
    led.append(
        row(logical_call_id="L2", attempt=1, cost_class="unknown", cost_usd=None, input_tokens=None)
    )
    led.append(row(logical_call_id="L2", attempt=2))
    led.append(row(logical_call_id="L3", attempt=0, cost_class="replay", cost_usd=0.0, cache="hit"))
    led.close()
    s = summarize(tmp_path / "ledger.jsonl")
    assert s["attempts"] == 3 and s["logical_calls"] == 3
    assert s["calculated_usd"] == 2 * 0.0000126 and s["unknown_attempts"] == 1
    assert s["replays"] == 1 and s["retried_calls"] == 1
    assert s["input_tokens"] == 600


def test_summary_on_missing_file(tmp_path):
    s = summarize(tmp_path / "ledger.jsonl")
    assert s["attempts"] == 0 and s["calculated_usd"] == 0.0
    assert s["p50_request_ms"] is None and s["by_status"] == {}


def test_pending_without_final_counts_as_unknown(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(row(cost_class="pending", cost_usd=None, input_tokens=None))
    led.close()
    s = summarize(tmp_path / "ledger.jsonl")
    assert s["attempts"] == 1 and s["unknown_attempts"] == 1
    assert s["logical_calls"] == 1 and s["by_status"] == {"none": 1}


def test_pending_with_final_row_is_not_double_counted(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(row(cost_class="pending", cost_usd=None, input_tokens=None))
    led.append(row())
    led.close()
    s = summarize(tmp_path / "ledger.jsonl")
    assert s["attempts"] == 1 and s["unknown_attempts"] == 0
    assert s["calculated_usd"] == 0.0000126


def test_request_ms_percentiles_and_by_status(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    for i, ms in enumerate([100.0, 200.0, 300.0], start=1):
        led.append(
            row(logical_call_id=f"L{i}", http_status=200, request_ms=ms)
        )
    led.append(row(logical_call_id="LX", http_status=None, request_ms=None, cost_class="unknown"))
    led.close()
    s = summarize(tmp_path / "ledger.jsonl")
    assert s["p50_request_ms"] == pytest.approx(200.0)
    assert s["by_status"] == {"200": 3, "none": 1}


def test_summarize_by_question_set(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(
        row(question_set="screen@0", input_tokens=300, http_status=200, request_ms=100.0)
    )
    led.append(
        row(
            logical_call_id="L2",
            question_set="deep@0",
            input_tokens=900,
            http_status=200,
            request_ms=300.0,
        )
    )
    led.append(
        row(
            logical_call_id="L3",
            question_set="deep@0",
            attempt=1,
            cost_class="unknown",
            cost_usd=None,
            input_tokens=None,
            http_status=None,
        )
    )
    led.append(
        row(
            logical_call_id="L4",
            question_set="deep@0",
            attempt=0,
            cost_class="replay",
            cost_usd=0.0,
        )
    )
    led.close()
    s = summarize(tmp_path / "ledger.jsonl", by="question_set")
    screen, deep = s["question_sets"]["screen@0"], s["question_sets"]["deep@0"]
    assert screen["calls"] == 1 and screen["input_tokens"] == 300
    assert screen["mean_tokens"] == 300 and screen["p50_ms"] == pytest.approx(100.0)
    assert deep["calls"] == 2 and deep["input_tokens"] == 900
    assert deep["mean_tokens"] == 900 and deep["unknown_attempts"] == 1
    assert deep["calculated_usd"] == 0.0000126

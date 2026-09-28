import math

import pytest

from atlas import contracts as c
from atlas.inference.estimate import (
    body_bytes,
    estimate_cost,
    fit_calibration,
    load_label,
)
from atlas.inference.ledger import Ledger

PRICE = 0.042e-6
PARENT = (
    "Synthetic parent: I run a tiny research agency and every Friday I copy "
    "vendor invoices into a spreadsheet by hand before billing clients."
)
TITLE = "Ask HN: What manual work do you still do every week?"


def _item(cid, n_sentences):
    sents = [
        f"Synthetic sentence number {i} about reconciling vendor invoices "
        "by hand every week."
        for i in range(n_sentences)
    ]
    return {
        "comment_id": cid,
        "comment": " ".join(sents),
        "parent": PARENT,
        "story_title": TITLE,
        "thread_type": "ask_hn",
        "sentences": sents,
    }


ITEMS = [
    _item(9_000_000_001, 1),
    _item(9_000_000_002, 4),
    _item(9_000_000_003, 16),
]
# measured in docs/measurements/2026-09-28-token-costs.md
MEASURED = {"screen@1": [498, 560, 776], "facets@1": [1423, 1530, 1938]}


def _ledger_row(cid, label, tokens):
    base = {k: None for k in c.LEDGER_FIELDS}
    base.update(
        run_id="m1",
        logical_call_id=f"{label}:{cid}:x1",
        attempt=1,
        comment_id=cid,
        question_set=label,
        input_tokens=tokens,
        cost_class="calculated",
        cost_usd=tokens * PRICE,
        model_requested="jev-1.13.0",
    )
    return base


def _write_ledger(path):
    led = Ledger(path)
    for label, toks in MEASURED.items():
        for item, t in zip(ITEMS, toks):
            led.append(_ledger_row(item["comment_id"], label, t))
    led.close()


def test_load_label_rejects_bad_format():
    with pytest.raises(ValueError):
        load_label("screen")
    with pytest.raises(ValueError):
        load_label("screen@x")


def test_calibrated_estimate_within_ten_percent(tmp_path):
    lp = tmp_path / "runs" / "m1" / "ledger.jsonl"
    _write_ledger(lp)
    cal = fit_calibration([lp], ITEMS)
    assert set(cal) == set(MEASURED)
    for label, toks in MEASURED.items():
        qs = load_label(label)
        assert cal[label]["n"] == 3
        for item, expected in zip(ITEMS, toks):
            est = estimate_cost(
                [item], qs, "jev-1.13.0", cal, usd_per_input_token=PRICE
            )
            assert est["method"] == "calibrated"
            assert est["est_input_tokens"] == pytest.approx(expected, rel=0.10)
            assert est["calls"] == 1
            assert est["est_usd"] == pytest.approx(
                est["est_input_tokens"] * PRICE
            )
            assert est["question_set"] == label


def test_fallback_bytes_over_3_2():
    qs = load_label("screen@1")
    est = estimate_cost(
        [ITEMS[0]], qs, "jev-1.13.0", {}, usd_per_input_token=PRICE
    )
    assert est["method"] == "bytes/3.2"
    assert est["est_input_tokens"] == math.ceil(
        body_bytes(ITEMS[0], qs, "jev-1.13.0") / 3.2
    )
    assert est["est_usd"] == pytest.approx(est["est_input_tokens"] * PRICE)


def test_rows_without_items_or_calculated_are_skipped(tmp_path):
    lp = tmp_path / "runs" / "m1" / "ledger.jsonl"
    _write_ledger(lp)
    cal = fit_calibration([lp], [ITEMS[0]])  # only one item keyed
    for label in MEASURED:
        assert cal[label]["n"] == 1

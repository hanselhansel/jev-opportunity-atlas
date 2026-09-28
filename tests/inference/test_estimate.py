import json
import math

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
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


def test_jev_estimate_cli(tmp_path, monkeypatch, capsys):
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "RUNS", runs)
    _write_ledger(runs / "m1" / "ledger.jsonl")
    (runs / "m1" / "run_manifest.json").write_text(
        json.dumps({"run_id": "m1", "budget": "measure"})
    )
    items_path = tmp_path / "items.parquet"
    pq.write_table(
        pa.table({k: [it[k] for it in ITEMS] for k in ITEMS[0]}), items_path
    )
    args = cli.build_parser().parse_args(
        ["jev", "estimate", "--set", "screen@1", "--items", str(items_path)]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["question_set"] == "screen@1"
    assert out["method"] == "calibrated"
    assert out["calls"] == 3
    assert out["est_input_tokens"] == pytest.approx(498 + 560 + 776, rel=0.10)
    assert out["est_usd"] == pytest.approx(out["est_input_tokens"] * PRICE)
    spent = sum(sum(t) for t in MEASURED.values()) * PRICE
    assert out["account_remaining_usd"] == pytest.approx(25.0 - spent)
    assert 0 < out["share_of_remaining"] < 1

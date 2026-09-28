"""Task 7.6: pilot report markdown and budget headroom."""

import json

import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.pilot import injected, packed, report, stages
from atlas.pilot.draw import pilot_draw
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    ledger_row,
    make_transport,
    mock_env,
    pilot_repo,
    write_ledger,
)

SAMPLE_ID = "pilot-7"
RUN_ID = "pilot-7"

SECTIONS = [
    "## Run",
    "## Cost",
    "## Tokens per call",
    "## Firsthand rate per design stratum",
    "## Latency",
    "## Answer distributions",
    "## Screen gate preview",
    "## Packed experiment",
    "## Injected cases",
    "## Projection",
    "## Calibration",
]


def _pipeline(monkeypatch, full=True):
    pilot_draw(SNAPSHOT_ID, n_target=80, min_per_stratum=10, seed=7)
    mock_env(monkeypatch, make_transport())
    stages.run_screen(SAMPLE_ID, RUN_ID, yes=True)
    if full:
        stages.run_facets(RUN_ID, yes=True)
        packed.run_packed(RUN_ID, n=20, k=5, yes=True)
        injected.run_injected(RUN_ID, yes=True)


def _section(md, heading):
    return md.split(heading, 1)[1].split("\n## ", 1)[0]


def test_full_report_sections(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _pipeline(monkeypatch)
    (paths.run_dir(RUN_ID) / "eval_calibration.json").write_text(
        json.dumps(
            {
                "n_labeled": 150,
                "n_yes": 60,
                "n_no": 90,
                "threshold": {"threshold": 0.45},
                "stop_rule": {"met": True},
            }
        )
    )
    capsys.readouterr()
    md = report.build_report(RUN_ID)
    headings = [l for l in md.splitlines() if l.startswith("## ")]
    assert headings == SECTIONS

    cost = _section(md, "## Cost")
    for line in cost.splitlines():
        if "$" in line:
            assert line.endswith(
                "(calculated from reported usage; not provider-reconciled)"
            ), line
    assert "pilot budget" in cost and "account" in cost

    sample = pq.read_table(paths.sample_path(SAMPLE_ID))
    firsthand = _section(md, "## Firsthand rate per design stratum")
    for s in set(sample.column("stratum").to_pylist()):
        assert s in firsthand

    projection = _section(md, "## Projection")
    for budget in ("5.00", "6.50", "8.00"):
        assert f"${budget}" in projection
    assert "expected firsthand" in projection

    packed_section = _section(md, "## Packed experiment")
    assert "n=20" in packed_section
    assert "tokens/comment" in packed_section

    injected_section = _section(md, "## Injected cases")
    assert "/20" in injected_section
    assert "overall" in injected_section

    gate = _section(md, "## Screen gate preview")
    assert ">= 0.3" in gate and ">= 0.5" in gate and ">= 0.7" in gate
    assert "problem evidence" in gate

    cal = _section(md, "## Calibration")
    assert "calibration only; not a reported quality number" in cal
    assert "n_labeled=150" in cal


def test_screen_only_report(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _pipeline(monkeypatch, full=False)
    capsys.readouterr()
    md = report.build_report(RUN_ID)
    assert [l for l in md.splitlines() if l.startswith("## ")] == SECTIONS
    assert "not run" in _section(md, "## Packed experiment")
    assert "not run" in _section(md, "## Injected cases")
    assert "not run" in _section(md, "## Screen gate preview")
    assert "not available" in _section(md, "## Calibration")


def test_budget_headroom_sums_run_ledgers(pilot_repo):  # noqa: F811
    usd = 0.042e-6
    for run, budget, rows in (
        (
            "ra",
            "pilot",
            [
                ledger_row(9_000_000_001, "screen@1", 1000, run_id="ra"),
                ledger_row(
                    9_000_000_002,
                    "screen@1",
                    None,
                    cost_class="unknown",
                    run_id="ra",
                ),
            ],
        ),
        (
            "rb",
            "screen",
            [ledger_row(9_000_000_003, "screen@1", 2000, run_id="rb")],
        ),
    ):
        d = paths.run_dir(run)
        d.mkdir(parents=True, exist_ok=True)
        (d / "run_manifest.json").write_text(
            json.dumps(
                {"run_id": run, "budget": budget, "model": stages.MODEL}
            )
        )
        write_ledger(paths.ledger_path(run), rows)

    head = stages.budget_headroom("pilot")
    committed = (1000 + 8000) * usd
    assert head["budget"] == "pilot"
    assert head["cap_usd"] == 0.50
    assert head["committed_usd"] == pytest.approx(committed)
    assert head["remaining_usd"] == pytest.approx(0.50 - committed)
    assert head["account_total"] == 25.0
    assert head["account_committed_usd"] == pytest.approx(
        committed + 2000 * usd
    )
    assert head["account_remaining_usd"] == pytest.approx(
        25.0 - committed - 2000 * usd
    )

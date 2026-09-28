"""Task 7.7: `atlas pilot` CLI — parser wiring, paid-stage dry-run
hint, and the no-network report command."""

import json

import httpx
import pytest

from atlas import paths
from atlas.cli import build_parser
from atlas.pilot.draw import pilot_draw
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)

SAMPLE_ID = "pilot-7"
RUN_ID = "pilot-7"


def _draw():
    return pilot_draw(SNAPSHOT_ID, n_target=80, min_per_stratum=10, seed=7)


def _parse(argv):
    return build_parser().parse_args(argv)


def test_all_seven_subcommands_parse(pilot_repo):  # noqa: F811
    for argv in (
        ["pilot", "draw"],
        ["pilot", "screen", "--sample", SAMPLE_ID, "--run", RUN_ID],
        ["pilot", "facets", "--run", RUN_ID],
        ["pilot", "packed", "--run", RUN_ID],
        ["pilot", "injected", "--run", RUN_ID],
        ["pilot", "gold", "--run", RUN_ID, "--sample", SAMPLE_ID],
        ["pilot", "report", "--run", RUN_ID],
    ):
        args = _parse(argv)
        assert callable(args.func)


def test_paid_subcommands_default_budget_pilot(pilot_repo):  # noqa: F811
    for argv in (
        ["pilot", "screen", "--sample", SAMPLE_ID, "--run", RUN_ID],
        ["pilot", "facets", "--run", RUN_ID],
        ["pilot", "packed", "--run", RUN_ID],
        ["pilot", "injected", "--run", RUN_ID],
    ):
        args = _parse(argv)
        assert args.budget == "pilot"
        assert args.yes is False


def test_screen_dry_run_makes_zero_requests(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _draw()
    transport = httpx.MockTransport(lambda request: pytest.fail("dispatched"))
    mock_env(monkeypatch, transport)
    args = _parse(["pilot", "screen", "--sample", SAMPLE_ID, "--run", RUN_ID])
    args.func(args)
    out = capsys.readouterr()
    est = json.loads(out.out)
    assert est["question_set"] == "screen@1"
    assert est["budget"] == "pilot"
    assert "dry run: nothing dispatched; re-run with --yes to spend" in out.err
    assert not paths.run_dir(RUN_ID).exists()


def test_screen_yes_dispatches(pilot_repo, monkeypatch, capsys):  # noqa: F811
    table = _draw()
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    args = _parse(
        ["pilot", "screen", "--sample", SAMPLE_ID, "--run", RUN_ID, "--yes"]
    )
    args.func(args)
    assert len(seen) == table.num_rows
    summary = json.loads(capsys.readouterr().out.strip().rsplit("\n", 1)[-1])
    assert summary["dispatched"] is True


def test_report_makes_no_network_call(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _draw()
    mock_env(monkeypatch, make_transport())
    args = _parse(
        ["pilot", "screen", "--sample", SAMPLE_ID, "--run", RUN_ID, "--yes"]
    )
    args.func(args)
    capsys.readouterr()

    monkeypatch.setattr(
        httpx.AsyncClient, "send", lambda *a, **k: pytest.fail("network")
    )
    monkeypatch.setattr(
        httpx.Client, "send", lambda *a, **k: pytest.fail("network")
    )
    args = _parse(["pilot", "report", "--run", RUN_ID])
    args.func(args)
    printed = capsys.readouterr().out
    assert printed.startswith("# Pilot report")
    out_path = paths.run_dir(RUN_ID) / "pilot_report.md"
    assert out_path.exists()
    assert printed == out_path.read_text(encoding="utf-8") + "\n"

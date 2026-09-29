"""Task 18.5: `atlas benchmark run|report` through the real CLI parser."""

import json

import pytest

from atlas import cli, paths
from tests.benchmark.test_support import bench_configs, write_benchmark_json
from tests.pilot.test_support import (  # noqa: F401
    make_transport,
    mock_env,
    pilot_repo,
)

RUN_ID = "bench-cli"

CASES = {
    "version": 1,
    "note": "cli test cases",
    "cases": [
        {
            "id": 9400000001,
            "category": "genuine_firsthand",
            "text": "PAIN our exports silently drop rows.",
            "expected": {
                "firsthand_problem": "yes",
                "account_type": "firsthand_account",
                "workaround": "yes",
                "card": "c07",
            },
            "why": "t",
        },
        {
            "id": 9400000002,
            "category": "one_line_reaction",
            "text": "Same here.",
            "expected": {
                "firsthand_problem": "no",
                "account_type": "other",
            },
            "why": "t",
        },
    ],
}


@pytest.fixture
def cli_repo(pilot_repo):  # noqa: F811
    return bench_configs(pilot_repo, CASES)


def _run(*argv):
    args = cli.build_parser().parse_args(["benchmark", *argv])
    args.func(args)


def test_run_without_yes_prints_estimates_and_dispatches_nothing(
    cli_repo, monkeypatch, capsys
):
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    _run("run", "--run", RUN_ID)
    assert seen == []
    out = capsys.readouterr().out
    assert '"question_set": "screen@1"' in out
    assert '"question_set": "facets@2"' in out
    assert "total_usd" in out
    assert not paths.run_dir(RUN_ID).exists()


def test_report_writes_markdown(cli_repo, capsys):
    write_benchmark_json(RUN_ID, n_cases=len(CASES["cases"]))
    _run("report", "--run", RUN_ID)
    md = paths.run_dir(RUN_ID) / "benchmark_report.md"
    assert md.exists()
    assert md.read_text(encoding="utf-8").splitlines()[0] == (
        "# Synthetic benchmark (invented cases; not real-data accuracy)"
    )
    assert json.loads(
        (paths.run_dir(RUN_ID) / "benchmark_score.json").read_text()
    )["n_cases"] == 2

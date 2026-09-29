"""L17 17.5: `atlas screen run|table` CLI wiring."""

import json

from atlas import paths
from tests.pilot.test_support import pilot_repo  # noqa: F401
from tests.screen import support

RUN_ID = "screen-r1"


def run_cli(*argv):
    from atlas import cli

    args = cli.build_parser().parse_args(list(argv))
    args.func(args)


def test_screen_run_dry_then_dispatch_and_table(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    sid, _ids = support.write_sample()
    seen = []
    support.mock_runtime(monkeypatch, seen=seen)

    run_cli(
        "screen", "run",
        "--sample", sid, "--run", RUN_ID, "--chunk", "200",
    )
    assert seen == []
    assert not paths.run_dir(RUN_ID).exists()
    capsys.readouterr()

    run_cli(
        "screen", "run",
        "--sample", sid, "--run", RUN_ID, "--chunk", "200", "--yes",
    )
    assert len(seen) == 200
    lines = capsys.readouterr().out.splitlines()
    totals = json.loads(lines[-1])
    assert totals["new_requests"] == 200
    assert totals["completed"] == 200

    run_cli("screen", "table", "--run", RUN_ID)
    out = json.loads(capsys.readouterr().out)
    assert out["rows"] == 1000
    assert out["path"].endswith("screen_by_comment.parquet")

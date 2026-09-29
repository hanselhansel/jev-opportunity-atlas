"""L23 task 23.2: --rpm and --concurrency flags on the paid cards commands.

The scratch run wrapped RunContext with functools.partial(rpm=1000); these
flags make that a first-class option. Everything runs on the mock transport.
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
from atlas.cards.engine import cli as cards_cli
from atlas.inference import keys
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[3]


def _configs(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    for name in ("example.t0.yaml", "planted.v1.yaml"):
        src = ROOT / "configs" / "cards" / name
        (configs / "cards" / name).write_bytes(src.read_bytes())
    monkeypatch.setattr(paths, "CONFIGS", configs)
    return configs


def _yes_env(tmp_path, monkeypatch, transport):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(cards_cli, "_transport", lambda: transport)


def _items_file(tmp_path):
    rows = [
        {
            "comment_id": 9_000_000_501,
            "pain_sentence": "synthetic ci pain",
            "sentences": ["synthetic ci pain"],
        }
    ]
    path = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    return str(path)


def _assign_args(items, *extra):
    return [
        "cards", "assign", "--cardset", "example", "--version", "t0",
        "--run", "r1", "--items", items, *extra,
    ]


def test_paid_commands_accept_rpm_and_concurrency():
    parser = cli.build_parser()
    assign = parser.parse_args(_assign_args("x.parquet"))
    assert assign.rpm == 1000 and assign.concurrency == 8
    merge = parser.parse_args(
        ["cards", "merge", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--rpm", "250.5", "--concurrency", "3"]
    )
    assert merge.rpm == 250.5 and merge.concurrency == 3
    verify = parser.parse_args(
        ["cards", "verify", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--rpm", "10"]
    )
    assert verify.rpm == 10 and verify.concurrency == 8
    planted = parser.parse_args(
        ["cards", "planted", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--concurrency", "2"]
    )
    assert planted.rpm == 1000 and planted.concurrency == 2


def test_run_ctx_passes_rpm_and_concurrency(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(tmp_path, monkeypatch, make_transport(seen=seen))
    captured = {}
    real_rc = cards_cli.RunContext

    def recording_rc(**kwargs):
        captured.update(kwargs)
        return real_rc(**kwargs)

    monkeypatch.setattr(cards_cli, "RunContext", recording_rc)
    args = cli.build_parser().parse_args(_assign_args(_items_file(tmp_path), "--yes"))
    args.func(args)
    capsys.readouterr()
    assert captured["rpm"] == 1000 and captured["concurrency"] == 8

    captured.clear()
    args = cli.build_parser().parse_args(
        _assign_args(
            _items_file(tmp_path),
            "--run", "r2",
            "--rpm", "600",
            "--concurrency", "2",
            "--yes",
        )
    )
    args.func(args)
    assert captured["rpm"] == 600 and captured["concurrency"] == 2


def test_rpm_builds_a_limiter(tmp_path, monkeypatch, capsys):
    _yes_env(tmp_path, monkeypatch, make_transport())
    captured = {}
    real_rc = cards_cli.RunContext
    monkeypatch.setattr(
        cards_cli,
        "RunContext",
        lambda **kw: captured.setdefault("ctx", real_rc(**kw)),
    )
    args = cli.build_parser().parse_args(_assign_args(_items_file(tmp_path), "--yes"))
    args.func(args)
    ctx = captured["ctx"]
    assert ctx.limiter is not None
    assert ctx.limiter.rate == pytest.approx(1000 / 60.0)

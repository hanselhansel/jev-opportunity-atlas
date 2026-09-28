import json

import pytest

import atlas.inference.cli as jev_cli
from atlas import cli, paths
from atlas import contracts as c
from atlas.inference import keys
from atlas.inference.ledger import Ledger, summarize
from tests.inference.mock_jev import make_transport

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def row(**over):
    base = {k: None for k in c.LEDGER_FIELDS}
    base.update(run_id="r1", logical_call_id="L1", attempt=1, question_set="screen@0",
                cost_class="calculated", cost_usd=0.0000126, input_tokens=300,
                http_status=200, request_ms=12.0, cache="miss")
    base.update(over)
    return base


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def test_jev_ledger_prints_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    led = Ledger(paths.ledger_path("r1"))
    led.append(row())
    led.append(row(logical_call_id="L2", cost_class="unknown", cost_usd=None,
                   input_tokens=None, http_status=None))
    led.close()
    args = _parse(["jev", "ledger", "--run", "r1"])
    args.func(args)
    assert json.loads(capsys.readouterr().out) == summarize(paths.ledger_path("r1"))


def test_jev_ledger_by_question_set(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    led = Ledger(paths.ledger_path("r1"))
    led.append(row())
    led.close()
    args = _parse(["jev", "ledger", "--run", "r1", "--by", "question_set"])
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["question_sets"]["screen@0"]["calls"] == 1


def _smoke_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(
        jev_cli, "_transport", lambda: make_transport([], on_request=None)
    )


def test_jev_smoke_deep_through_mock(tmp_path, monkeypatch, capsys):
    _smoke_env(tmp_path, monkeypatch)
    args = _parse(["jev", "smoke", "--set", "deep"])
    args.func(args)
    captured = capsys.readouterr().out
    out = json.loads(captured)
    assert out["run"]["completed"] == 1 and out["ledger"]["attempts"] == 1
    assert out["checks"] and all(out["checks"].values())
    assert list((tmp_path / "runs").glob("smoke-*/ledger.jsonl"))
    assert CANARY not in captured


def test_jev_smoke_screen_through_mock(tmp_path, monkeypatch, capsys):
    _smoke_env(tmp_path, monkeypatch)
    args = _parse(["jev", "smoke"])
    args.func(args)
    captured = capsys.readouterr().out
    out = json.loads(captured)
    assert out["run"]["completed"] == 1 and out["ledger"]["attempts"] == 1
    assert out["checks"] == {}
    assert CANARY not in captured


def test_jev_smoke_unknown_budget_exits(tmp_path, monkeypatch):
    _smoke_env(tmp_path, monkeypatch)
    args = _parse(["jev", "smoke", "--budget", "nope"])
    with pytest.raises(SystemExit):
        args.func(args)

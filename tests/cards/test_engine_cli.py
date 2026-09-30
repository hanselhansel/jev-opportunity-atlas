"""Task 11.8: cards CLI registration, dry-run estimates, and the --yes path."""

import argparse
import json
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
from atlas.cards.engine import cli as cards_cli
from atlas.cards.engine.planted import load_planted
from atlas.inference import keys
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[2]


def _fresh_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    cards_cli.register(sub)
    return parser


def _parse(argv):
    return cli.build_parser().parse_args(argv)


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


def _items_file(tmp_path):
    rows = [
        {"comment_id": 9_000_000_501, "pain_sentence": "ci keeps failing",
         "sentences": ["ci keeps failing"]},
        {"comment_id": 9_000_000_502, "pain_sentence": "invoices by hand",
         "sentences": ["invoices by hand"]},
        {"comment_id": 9_000_000_503, "pain_sentence": "unmatched pain",
         "sentences": ["unmatched pain"]},
    ]
    path = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    return str(path)


def _chooser(state, qid, options):
    problem = state["problem"]
    if qid == "group":
        return {"ci keeps failing": "g01", "invoices by hand": "g02"}.get(
            problem, "none"
        )
    return {"ci keeps failing": "c0001", "invoices by hand": "c0003"}.get(
        problem, "none"
    )


def _yes_env(tmp_path, monkeypatch, transport):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(cards_cli, "_transport", lambda: transport)


def test_register_on_fresh_parser():
    parser = _fresh_parser()
    args = parser.parse_args(
        ["cards", "residue", "--run", "r1", "--version", "t0"]
    )
    assert args.cards_command == "residue" and args.k == 200 and args.seed == 1


def test_cards_in_build_parser():
    args = _parse(["cards", "residue", "--run", "r1", "--version", "t0"])
    assert args.cards_command == "residue"
    args = _parse(
        ["cards", "assign", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--items", "x.parquet"]
    )
    assert args.cards_command == "assign" and args.budget == "assign"
    args = _parse(
        ["cards", "planted", "--cardset", "example", "--version", "t0",
         "--run", "r1"]
    )
    assert args.budget == "merge_verify" and args.planted == "v1"


def test_assign_dry_run_prints_estimate_only(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(cards_cli, "_transport", lambda: pytest.fail("client"))
    args = _parse(
        ["cards", "assign", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--items", _items_file(tmp_path)]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "assign"
    assert out["estimated_calls"] == 6  # level 1 + level-2 upper bound
    assert out["estimated_input_tokens"] > 0
    assert out["estimated_usd"] > 0 and out["budget"] == "assign"
    budgets = tomllib.loads((paths.CONFIGS / "budgets.toml").read_text())
    assert out["cap_usd"] == budgets["assign"]
    assert not (tmp_path / "runs").exists() or not list(
        (tmp_path / "runs").rglob("*.parquet")
    )


def test_unknown_budget_exits(tmp_path, monkeypatch):
    _configs(tmp_path, monkeypatch)
    args = _parse(
        ["cards", "assign", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--budget", "nope", "--items", _items_file(tmp_path)]
    )
    with pytest.raises(SystemExit):
        args.func(args)


def test_assign_yes_then_residue(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(tmp_path, monkeypatch, make_transport(chooser=_chooser, seen=seen))
    args = _parse(
        ["cards", "assign", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--items", _items_file(tmp_path), "--yes"]
    )
    args.func(args)
    captured = capsys.readouterr().out
    assert CANARY not in captured
    assert len(seen) == 5  # 3 groups + 2 cards (none-group skips level 2)
    run_dir = tmp_path / "runs" / "r1"
    table = pq.read_table(run_dir / "assignments-t0.parquet")
    rows = {r["comment_id"]: r for r in table.to_pylist()}
    assert rows[9_000_000_501]["card_id"] == "c0001"
    assert rows[9_000_000_502]["card_id"] == "c0003"
    assert rows[9_000_000_503]["group_id"] == "none"
    assert pq.read_table(run_dir / "pain.parquet").num_rows == 3
    capsys.readouterr()
    args = _parse(
        ["cards", "residue", "--run", "r1", "--version", "t0"]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["n_total"] == 3 and out["n_residue"] == 1
    assert out["sample"] == [9_000_000_503]


def test_planted_yes_writes_result_json(tmp_path, monkeypatch, capsys):
    planted = load_planted("v1")
    truth = {c["text"]: c["card_id"] for c in planted.comments}

    def chooser(state, qid, options):
        card = truth.get(state["problem"])
        if qid == "group":
            return "gp1" if card else "none"
        return card or "none"

    _yes_env(tmp_path, monkeypatch, make_transport(chooser=chooser))
    args = _parse(
        ["cards", "planted", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--yes"]
    )
    args.func(args)
    out = capsys.readouterr().out
    dec = json.JSONDecoder()
    _, end = dec.raw_decode(out, out.index("{"))
    printed, _ = dec.raw_decode(out, out.index("{", end))
    assert printed["recovery"] == 1.0
    assert printed["decoy_false_rate"] == 0.0
    assert printed["n_planted"] == 50 and printed["n_decoys"] == 10
    path = tmp_path / "runs" / "r1" / "planted-t0+planted-v1.json"
    assert path.exists()
    assert json.loads(path.read_text()) == printed


def test_verify_yes_rewrites_assignments(tmp_path, monkeypatch, capsys):
    _yes_env(
        tmp_path,
        monkeypatch,
        make_transport(chooser=_chooser, noul=lambda s, q: 0.42),
    )
    items = _items_file(tmp_path)
    args = _parse(
        ["cards", "assign", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--items", items, "--yes"]
    )
    args.func(args)
    capsys.readouterr()
    args = _parse(
        ["cards", "verify", "--cardset", "example", "--version", "t0",
         "--run", "r1", "--yes"]
    )
    args.func(args)
    rows = {
        r["comment_id"]: r
        for r in pq.read_table(
            tmp_path / "runs" / "r1" / "assignments-t0.parquet"
        ).to_pylist()
    }
    assert rows[9_000_000_501]["verified_p"] == 0.42
    assert rows[9_000_000_502]["verified_p"] == 0.42
    assert rows[9_000_000_503]["verified_p"] is None

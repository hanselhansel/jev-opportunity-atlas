"""Task 25.3: `robust assign-paraphrase` runs `assign` with the reworded
instructions under budget `robustness`, printing an estimate first."""

import json
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
from atlas.inference import keys
from atlas.robustness import cli as robust_cli
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[2]


def _configs(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    for name in ("example.t0.yaml", "paraphrases.v1.json"):
        src = ROOT / "configs" / "cards" / name
        (configs / "cards" / name).write_bytes(src.read_bytes())
    monkeypatch.setattr(paths, "CONFIGS", configs)


def _items_file(tmp_path):
    rows = [
        {"comment_id": 9_000_000_801, "pain_sentence": "ci keeps failing",
         "sentences": ["ci keeps failing"]},
        {"comment_id": 9_000_000_802, "pain_sentence": "invoices by hand",
         "sentences": ["invoices by hand"]},
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


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def _yes_env(tmp_path, monkeypatch, transport):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(robust_cli, "_transport", lambda: transport)


def test_assign_paraphrase_parses():
    args = _parse(
        [
            "robust", "assign-paraphrase", "--cardset", "example",
            "--version", "t0", "--items", "x.parquet", "--run", "rp1",
            "--para", "2",
        ]
    )
    assert args.robust_cmd == "assign-paraphrase"
    assert args.para == 2 and args.budget == "robustness"
    assert args.rpm == 1000 and args.yes is False


def test_assign_paraphrase_dry_run(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(robust_cli, "_transport", lambda: pytest.fail("client"))
    args = _parse(
        [
            "robust", "assign-paraphrase", "--cardset", "example",
            "--version", "t0", "--items", _items_file(tmp_path),
            "--run", "rp1", "--para", "1",
        ]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "assign-para1"
    assert out["estimated_calls"] == 4  # level 1 + level-2 upper bound
    budgets = tomllib.loads((paths.CONFIGS / "budgets.toml").read_text())
    assert out["budget"] == "robustness" and out["cap_usd"] == budgets["robustness"]
    assert not (tmp_path / "runs").exists()


def test_assign_paraphrase_yes_uses_para_instructions(
    tmp_path, monkeypatch, capsys
):
    seen = []
    _yes_env(tmp_path, monkeypatch, make_transport(chooser=_chooser, seen=seen))
    items = _items_file(tmp_path)
    args = _parse(
        [
            "robust", "assign-paraphrase", "--cardset", "example",
            "--version", "t0", "--items", items, "--run", "rp1",
            "--para", "1", "--yes",
        ]
    )
    args.func(args)
    captured = capsys.readouterr().out
    assert CANARY not in captured

    paras = json.loads(
        (ROOT / "configs" / "cards" / "paraphrases.v1.json").read_text()
    )["paraphrases"]["1"]
    bodies = [json.loads(r.content) for r in seen]
    groups = [b for b in bodies if "group" in b["questions"]]
    cards = [b for b in bodies if "card" in b["questions"]]
    assert len(groups) == 2 and len(cards) == 2
    for b in groups:
        assert b["questions"]["group"]["instructions"] == paras[
            "group_instructions"
        ]
    for b in cards:
        assert b["questions"]["card"]["instructions"] == paras[
            "card_instructions"
        ]
    labels = {
        json.loads(line)["question_set"]
        for line in (tmp_path / "runs" / "rp1" / "done.jsonl")
        .read_text()
        .splitlines()
    }
    assert labels == {"assign-para1-g@t0", "assign-para1-c@t0"}
    table = pq.read_table(
        tmp_path / "runs" / "rp1" / "assignments-t0.parquet"
    )
    rows = {r["comment_id"]: r for r in table.to_pylist()}
    assert rows[9_000_000_801]["card_id"] == "c0001"
    assert rows[9_000_000_802]["card_id"] == "c0003"

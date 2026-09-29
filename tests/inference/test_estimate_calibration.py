"""L31 task 31.2: printed estimates carry the calibrated figure.

configs/prices.toml [estimate_calibration] scales each command family's
bytes/3.2 estimate; every estimate JSON keeps the raw USD beside the
calibrated one and records the multipliers applied.
"""

import json
from pathlib import Path

import pytest

from atlas import cli, paths
from atlas.inference.estimate import estimate_multiplier
from tests.cards.engine.test_budget_stop import (
    _assign_items,
    _assignment,
    _write_facets_sample,
    _write_run,
)
from tests.cards.test_engine_support import PRICE
from tests.pilot.test_support import SNAPSHOT_ID, pilot_repo  # noqa: F401
from tests.screen.support import write_sample

ROOT = Path(__file__).resolve().parents[2]


def _configs(tmp_path, monkeypatch, card_files=()):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    for name in card_files:
        src = ROOT / "configs" / "cards" / name
        (configs / "cards" / name).write_bytes(src.read_bytes())
    monkeypatch.setattr(paths, "CONFIGS", configs)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    return configs


def test_estimate_multiplier_table():
    expected = {
        "assign_card": 1.4,
        "assign_group": 1.1,
        "verify": 2.0,
        "merge": 1.3,
        "replies": 1.3,
        "facets": 1.15,
        "screen": 1.0,
    }
    for family, want in expected.items():
        assert estimate_multiplier(family) == want
    assert estimate_multiplier("unlisted_family") == 1.0


def test_assign_estimate_calibrates_per_family(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch, card_files=("example.t0.yaml",))
    items = _assign_items(tmp_path)
    args = cli.build_parser().parse_args(
        [
            "cards", "assign", "--cardset", "example", "--version", "t0",
            "--run", "r1", "--items", items,
        ]
    )
    args.func(args)  # no --yes: the estimate is the whole output
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "assign"
    assert out["calibration"] == {"assign_group": 1.1, "assign_card": 1.4}
    assert out["estimated_calls"] == 6
    assert out["estimated_usd_raw"] == pytest.approx(
        out["estimated_input_tokens"] * PRICE
    )

    import pyarrow.parquet as pq

    from atlas.cards.engine import cli as cards_cli
    from atlas.cards.engine.cardset import load_cardset

    cs = load_cardset("example", "t0")
    fam = cards_cli._assign_tokens(pq.read_table(items).to_pylist(), cs)
    expected = (
        sum(fam["assign_group"]) * 1.1 + sum(fam["assign_card"]) * 1.4
    ) * PRICE
    assert out["estimated_usd"] == pytest.approx(expected)
    assert out["estimated_usd"] > out["estimated_usd_raw"]


def test_merge_estimate_calibrates(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch, card_files=("example.t0.yaml",))
    _write_run(paths.run_dir("r1"), [_assignment(9_000_000_501)])
    args = cli.build_parser().parse_args(
        [
            "cards", "merge", "--cardset", "example", "--version", "t0",
            "--run", "r1", "--all-pairs",
        ]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "merge"
    assert out["calibration"] == {"merge": 1.3}
    assert out["estimated_calls"] == 3
    assert out["estimated_usd"] == pytest.approx(
        out["estimated_usd_raw"] * 1.3
    )


def test_verify_estimate_calibrates(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch, card_files=("example.t0.yaml",))
    _write_run(paths.run_dir("r1"), [_assignment(9_000_000_501)])
    args = cli.build_parser().parse_args(
        [
            "cards", "verify", "--cardset", "example", "--version", "t0",
            "--run", "r1",
        ]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "verify"
    assert out["calibration"] == {"verify": 2.0}
    assert out["estimated_usd"] == pytest.approx(
        out["estimated_usd_raw"] * 2.0
    )


def test_facets_estimate_calibrates(pilot_repo):  # noqa: F811
    import pyarrow.parquet as pq

    from atlas.facets.phase2 import estimate_phase2

    comments = pq.read_table(
        paths.snapshot_dir(SNAPSHOT_ID) / "comments.parquet",
        columns=["id", "eligible"],
    )
    ids = sorted(r["id"] for r in comments.to_pylist() if r["eligible"])[:10]
    _write_facets_sample("fac-cal", ids)
    est = estimate_phase2("fac-cal")
    assert est["calibration"] == {"facets": 1.15}
    assert est["est_usd"] == pytest.approx(
        est["est_usd_raw"] * 1.15, abs=0.002
    )


def test_screen_estimate_calibrates(pilot_repo, capsys):  # noqa: F811
    sid, _ids = write_sample("scr-cal", n=10)
    args = cli.build_parser().parse_args(
        ["screen", "run", "--sample", sid, "--run", "scr-cal1"]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["calibration"] == {"screen": 1.0}
    assert out["usd"] == pytest.approx(out["usd_raw"])

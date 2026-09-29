"""L23 task 23.3: `merge_pairs(..., all_pairs=True)` scores every pair of
active cards across all groups, and `cards merge --all-pairs` exposes it.

example.t0 has three active cards (c0001, c0002 in g01; c0003 in g02), one
draft, and one merged card, so all-pairs yields C(3,2) = 3 pairs while the
default yields the single within-group pair.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import cli, contracts, paths
from atlas.cards.engine.assign import AssignResult
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.merge import merge_pairs

ROOT = Path(__file__).resolve().parents[3]


def _cs():
    return load_cardset("example", "t0")


def test_all_pairs_returns_every_active_pair():
    cs = _cs()
    pairs = merge_pairs(cs, AssignResult(), all_pairs=True)
    assert pairs == [("c0001", "c0002"), ("c0001", "c0003"), ("c0002", "c0003")]
    n = len(cs.cards)
    assert len(pairs) == n * (n - 1) // 2
    # Cross-group pairs appear with no top2 overlap evidence at all.
    assert ("c0001", "c0003") in pairs


def test_all_pairs_sorted_and_excludes_inactive():
    cs = _cs()
    pairs = merge_pairs(cs, AssignResult(), all_pairs=True)
    assert pairs == sorted(pairs)
    flat = {c for pair in pairs for c in pair}
    assert "c0004" not in flat  # draft
    assert "c0005" not in flat  # merged_into:c0003


def test_default_unchanged():
    cs = _cs()
    pairs = merge_pairs(cs, AssignResult())
    assert pairs == [("c0001", "c0002")]
    pairs_kw = merge_pairs(cs, AssignResult(), all_pairs=False)
    assert pairs_kw == pairs


def _write_assignments(run_dir):
    row = {f.name: None for f in contracts.ASSIGNMENTS}
    row.update(
        run_id="r1",
        comment_id=9_000_000_501,
        taxonomy_version="t0",
        group_id="g01",
        card_id="c0001",
    )
    pq.write_table(
        pa.Table.from_pylist([row], schema=contracts.ASSIGNMENTS),
        run_dir / "assignments-t0.parquet",
    )


def test_merge_all_pairs_flag_scales_estimate(tmp_path, monkeypatch, capsys):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    (configs / "cards" / "example.t0.yaml").write_bytes(
        (ROOT / "configs" / "cards" / "example.t0.yaml").read_bytes()
    )
    monkeypatch.setattr(paths, "CONFIGS", configs)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    run_dir = paths.run_dir("r1")
    run_dir.mkdir(parents=True)
    _write_assignments(run_dir)

    base = ["cards", "merge", "--cardset", "example", "--version", "t0",
            "--run", "r1"]
    args = cli.build_parser().parse_args(base)
    args.func(args)
    assert json.loads(capsys.readouterr().out)["estimated_calls"] == 1

    args = cli.build_parser().parse_args([*base, "--all-pairs"])
    args.func(args)
    assert json.loads(capsys.readouterr().out)["estimated_calls"] == 3

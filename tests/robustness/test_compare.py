"""Task 25.4: `robust compare-screen` and `robust compare-assign` on synthetic
runs, with the expected numbers computed by hand."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.robustness.compare import compare_assign, compare_screen
from atlas.screen.unpack import SCREEN_BY_COMMENT

CIDS = [9_000_000_000 + i for i in range(8)]
# strata a x4 (weight 10), b x4 (weight 20); total weight 120
WEIGHTS = [10.0] * 4 + [20.0] * 4
MAIN_P = [0.9, 0.8, 0.2, 0.1, 0.85, 0.75, 0.3, 0.4]
PARA_P = [0.95, 0.7, 0.1, 0.15, 0.9, 0.6, 0.25, 0.45]


def _write_sample(tmp_path, monkeypatch, sample_id="sub"):
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    paths.SAMPLES.mkdir(parents=True)
    rows = [
        {
            "sample_id": sample_id,
            "comment_id": cid,
            "story_id": 9_000_100_000 + i % 3,
            "stratum": "a" if i < 4 else "b",
            "inclusion_prob": 1.0 / WEIGHTS[i],
            "weight": WEIGHTS[i],
            "batch": 1,
            "draw_order": i,
        }
        for i, cid in enumerate(CIDS)
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.SAMPLE),
        paths.sample_path(sample_id),
    )


def _write_screen_table(run_id, probs):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True)
    rows = [
        {
            "comment_id": cid,
            "story_id": 9_000_100_000 + i % 3,
            "stratum": "a" if i < 4 else "b",
            "weight": WEIGHTS[i],
            "half": "explore",
            "firsthand_p": p,
            "packed_id": cid,
            "slot": "c1",
            "model_returned": "jev-1.13.0",
            "request_id": f"req-{cid}",
        }
        for i, (cid, p) in enumerate(zip(CIDS, probs))
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=SCREEN_BY_COMMENT),
        run_dir / "screen_by_comment.parquet",
    )


def test_compare_screen_hand_computed(tmp_path, monkeypatch):
    _write_sample(tmp_path, monkeypatch)
    _write_screen_table("main-run", MAIN_P)
    _write_screen_table("para-run", PARA_P)
    out = compare_screen(
        "main-run", ["para-run"], "sub", cutoff=0.7, n_boot=500, seed=1
    )
    assert out["main_run"] == "main-run" and out["sample_id"] == "sub"
    assert out["n_sample"] == 8
    main = out["runs"]["main-run"]
    # main positives: c1,c2,c5,c6 -> (10+10+20+20)/120
    assert main["prevalence"] == pytest.approx(0.5)
    assert main["ci_low"] <= main["prevalence"] <= main["ci_high"]
    para = out["runs"]["para-run"]
    # para positives: c1,c2,c5 -> (10+10+20)/120
    assert para["prevalence"] == pytest.approx(40 / 120)
    comp = para["vs_main"]
    assert comp["n"] == 8
    # only c6 differs on side of 0.7 (main 0.75, para 0.6)
    assert comp["agreement"] == pytest.approx(7 / 8)
    # p_o=0.875, p_e=0.5 -> kappa 0.75
    assert comp["kappa"] == pytest.approx(0.75)
    # ranks differ only at c3/c4: d^2 sum 2, n=8 -> 1 - 12/504
    assert comp["spearman"] == pytest.approx(1 - 12 / 504)
    # No text fields leak into the output.
    assert json.dumps(out).isascii()


def _assignment(cid, run_id, group, card):
    return {
        "run_id": run_id,
        "comment_id": cid,
        "taxonomy_version": "t0",
        "group_id": group,
        "group_p": 0.9,
        "group_confidence": 0.9,
        "card_id": card,
        "card_p": 0.9 if card else None,
        "card_confidence": 0.9 if card else None,
        "verified_p": None,
    }


MAIN_ASSIGN = [
    ("g01", "c01"), ("g01", "c02"), ("g02", "c03"),
    ("none", None), ("g02", "none"), ("g01", "c01"),
]
PARA_ASSIGN = [
    ("g01", "c01"), ("g01", "c01"), ("g02", "c03"),
    ("none", None), ("g01", "none"), ("g02", "c05"),
]


def _write_assignments(run_id, pairs):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True)
    rows = [
        _assignment(9_000_000_100 + i, run_id, g, c)
        for i, (g, c) in enumerate(pairs)
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / "assignments-t0.parquet",
    )


def test_compare_assign_hand_computed(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    _write_assignments("main-cards", MAIN_ASSIGN)
    _write_assignments("para-cards", PARA_ASSIGN)
    out = compare_assign("main-cards", ["para-cards"], "t0")
    assert out["main_run"] == "main-cards" and out["version"] == "t0"
    comp = out["runs"]["para-cards"]
    assert comp["n_common"] == 6
    # groups differ on c5 (g02->g01) and c6 (g01->g02)
    assert comp["group_agreement"] == pytest.approx(4 / 6)
    # cards differ on c2 (c02->c01) and c6 (c01->c05); none counts as a value
    assert comp["card_agreement"] == pytest.approx(4 / 6)
    shares = comp["card_shares"]
    # union of top-20 sets: c01, c02, c03 (main) + c01, c03, c05 (para)
    assert set(shares) == {"c01", "c02", "c03", "c05"}
    assert shares["c01"]["main"] == pytest.approx(2 / 6)
    assert shares["c01"]["run"] == pytest.approx(2 / 6)
    assert shares["c02"]["main"] == pytest.approx(1 / 6)
    assert shares["c02"]["run"] == pytest.approx(0.0)
    assert shares["c05"]["main"] == pytest.approx(0.0)
    assert shares["c05"]["run"] == pytest.approx(1 / 6)
    assert comp["max_abs_diff"] == pytest.approx(1 / 6)
    assert json.dumps(out).isascii()


def test_compare_commands_write_out(tmp_path, monkeypatch, capsys):
    from atlas import cli

    _write_sample(tmp_path, monkeypatch)
    _write_screen_table("main-run", MAIN_P)
    _write_screen_table("para-run", PARA_P)
    _write_assignments("main-cards", MAIN_ASSIGN)
    _write_assignments("para-cards", PARA_ASSIGN)
    screen_out = tmp_path / "cmp-screen.json"
    args = cli.build_parser().parse_args(
        [
            "robust", "compare-screen", "--main-run", "main-run",
            "--runs", "para-run", "--sample", "sub", "--cutoff", "0.7",
            "--n-boot", "200", "--out", str(screen_out),
        ]
    )
    args.func(args)
    out = json.loads(screen_out.read_text())
    assert out["runs"]["main-run"]["prevalence"] == pytest.approx(0.5)
    assign_out = tmp_path / "cmp-assign.json"
    args = cli.build_parser().parse_args(
        [
            "robust", "compare-assign", "--main-run", "main-cards",
            "--runs", "para-cards", "--version", "t0",
            "--out", str(assign_out),
        ]
    )
    args.func(args)
    out = json.loads(assign_out.read_text())
    assert out["runs"]["para-cards"]["card_agreement"] == pytest.approx(4 / 6)
    capsys.readouterr()

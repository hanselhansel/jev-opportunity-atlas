"""L28 task 28.1: `cards combine` merges several assign runs of one taxonomy
version into a new run directory.

Each input is read through load_assignments; overlapping comment_ids and rows
carrying a foreign taxonomy_version are refused. The output run gets
assignments-<version>.parquet + meta sidecar through write_assignments with
run_id re-stamped and rows sorted by comment_id, a deduplicated pain.parquet
(conflicting sentences for one comment_id are refused), and a
combine-<version>.json sidecar with per-run row counts and input sha256s.
answers/ are never copied: downstream readers need only the assignments table
and pain.parquet.
"""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.cards.engine import cli as cards_cli
from atlas.cards.engine import combine as combine_mod
from atlas.cards.engine.assign import (
    AssignResult,
    load_assignments,
    write_assignments,
)
from atlas.inference import keys

ROOT = Path(__file__).resolve().parents[3]
BASE = 9_000_000_000

MINI_T3 = """\
taxonomy_version: t3
groups:
  g1: {label: "Alpha needs"}
  g2: {label: "Beta needs"}
cards:
  - {card_id: a1, group_id: g1, statement: "alpha one need", status: approved}
  - {card_id: b1, group_id: g2, statement: "beta one need", status: approved}
"""


def _row(cid, run_id, card="a1", version="t3", card_p=0.9):
    return {
        "run_id": run_id,
        "comment_id": cid,
        "taxonomy_version": version,
        "group_id": "g1" if card != "b1" else "g2",
        "group_p": 0.9,
        "group_confidence": 0.9,
        "card_id": card,
        "card_p": card_p,
        "card_confidence": 0.9,
        "verified_p": None,
    }


def _pain(*pairs):
    return [
        {"comment_id": cid, "pain_sentence": sentence} for cid, sentence in pairs
    ]


def _write_run(run_id, rows, pain, version="t3", meta=None):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True)
    write_assignments(
        run_dir, AssignResult(rows=rows, meta=meta or {}), version
    )
    pq.write_table(
        pa.Table.from_pylist(pain, schema=combine_mod.PAIN_SCHEMA),
        run_dir / "pain.parquet",
    )
    return run_dir


@pytest.fixture
def runs_env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    return tmp_path


def test_combine_merges_sorts_restamps_and_sidecar(runs_env):
    meta1 = {
        BASE + 1: {
            "low_confidence": False,
            "card_top2": ["a1"],
            "group_probs": {"g1": 0.9},
            "card_probs": {"a1": 0.9},
        }
    }
    _write_run(
        "r1",
        [_row(BASE + 2, "r1"), _row(BASE + 1, "r1")],
        _pain((BASE + 1, "p1"), (BASE + 2, "p2")),
        meta=meta1,
    )
    _write_run("r2", [_row(BASE + 3, "r2", card="b1")],
               _pain((BASE + 3, "p3")))

    stats = combine_mod.combine(["r1", "r2"], "t3", "rc")

    out = paths.run_dir("rc")
    result = load_assignments(out, "t3")
    assert [r["comment_id"] for r in result.rows] == [
        BASE + 1,
        BASE + 2,
        BASE + 3,
    ]
    assert all(
        r["run_id"] == "rc" and r["taxonomy_version"] == "t3"
        for r in result.rows
    )
    assert result.meta[BASE + 1]["card_top2"] == ["a1"]

    pain = {
        r["comment_id"]: r["pain_sentence"]
        for r in pq.read_table(out / "pain.parquet").to_pylist()
    }
    assert pain == {BASE + 1: "p1", BASE + 2: "p2", BASE + 3: "p3"}

    side = json.loads((out / "combine-t3.json").read_text())
    assert side["run_id"] == "rc" and side["taxonomy_version"] == "t3"
    by_id = {s["run_id"]: s for s in side["source_runs"]}
    assert by_id["r1"]["rows"] == 2 and by_id["r2"]["rows"] == 1
    sha1 = hashlib.sha256(
        (paths.run_dir("r1") / "assignments-t3.parquet").read_bytes()
    ).hexdigest()
    assert by_id["r1"]["assignments_sha256"] == sha1
    assert stats == side


def test_combine_refuses_overlapping_comment_ids(runs_env):
    _write_run("r1", [_row(BASE + 1, "r1")], _pain((BASE + 1, "p1")))
    _write_run("r2", [_row(BASE + 1, "r2", card="b1")],
               _pain((BASE + 1, "p1")))
    with pytest.raises(combine_mod.CombineError, match="more than one"):
        combine_mod.combine(["r1", "r2"], "t3", "rc")
    assert not paths.run_dir("rc").exists()


def test_combine_refuses_foreign_taxonomy_version(runs_env):
    _write_run(
        "r1",
        [_row(BASE + 1, "r1", version="t2")],  # file is -t3, row says t2
        _pain((BASE + 1, "p1")),
    )
    with pytest.raises(combine_mod.CombineError, match="t2"):
        combine_mod.combine(["r1"], "t3", "rc")


def test_combine_refuses_output_run_in_inputs(runs_env):
    _write_run("r1", [_row(BASE + 1, "r1")], _pain((BASE + 1, "p1")))
    with pytest.raises(combine_mod.CombineError, match="input"):
        combine_mod.combine(["r1"], "t3", "r1")


def test_combine_refuses_empty_run_list(runs_env):
    with pytest.raises(combine_mod.CombineError, match="at least one"):
        combine_mod.combine([], "t3", "rc")


def test_combine_requires_assignments_file(runs_env):
    paths.run_dir("r1").mkdir(parents=True)
    with pytest.raises(combine_mod.CombineError, match="assignments-t3"):
        combine_mod.combine(["r1"], "t3", "rc")


def test_combine_requires_pain(runs_env):
    run_dir = paths.run_dir("r1")
    run_dir.mkdir(parents=True)
    write_assignments(
        run_dir, AssignResult(rows=[_row(BASE + 1, "r1")], meta={}), "t3"
    )
    with pytest.raises(combine_mod.CombineError, match="pain"):
        combine_mod.combine(["r1"], "t3", "rc")


def test_combine_dedups_pain_rows(runs_env):
    # BASE+9's assign call failed in both runs, so it appears in neither
    # assignments table but in both pain.parquet files.
    _write_run(
        "r1",
        [_row(BASE + 1, "r1")],
        _pain((BASE + 1, "p1"), (BASE + 9, "shared")),
    )
    _write_run(
        "r2",
        [_row(BASE + 2, "r2")],
        _pain((BASE + 2, "p2"), (BASE + 9, "shared")),
    )
    combine_mod.combine(["r1", "r2"], "t3", "rc")
    pain = pq.read_table(paths.run_dir("rc") / "pain.parquet").to_pylist()
    assert [(r["comment_id"], r["pain_sentence"]) for r in pain] == [
        (BASE + 1, "p1"),
        (BASE + 2, "p2"),
        (BASE + 9, "shared"),
    ]


def test_combine_refuses_conflicting_pain(runs_env):
    _write_run("r1", [_row(BASE + 1, "r1")], _pain((BASE + 9, "alpha")))
    _write_run("r2", [_row(BASE + 2, "r2")], _pain((BASE + 9, "different")))
    with pytest.raises(combine_mod.CombineError, match="pain"):
        combine_mod.combine(["r1", "r2"], "t3", "rc")


def _comment(cid, **over):
    row = {f.name: None for f in contracts.COMMENTS}
    row.update(id=cid, time=1000, text_norm="synthetic", state="ok")
    row.update(over)
    return row


def test_answers_not_copied_and_downstream_reads(runs_env, tmp_path,
                                               monkeypatch, capsys):
    """verify and replies need assignments + pain.parquet only; the combined
    run supplies both and carries no copied answers/ directory."""
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    (configs / "cards" / "mini.t3.yaml").write_text(MINI_T3, encoding="utf-8")
    monkeypatch.setattr(paths, "CONFIGS", configs)
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))

    _write_run(
        "r1",
        [_row(BASE + 1, "r1", card="a1"), _row(BASE + 2, "r1", card="none")],
        _pain((BASE + 1, "p1"), (BASE + 2, "p2")),
    )
    _write_run("r2", [_row(BASE + 3, "r2", card="b1")],
               _pain((BASE + 3, "p3")))
    answers_dir = paths.run_dir("r1") / "answers"
    answers_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist([], schema=contracts.ANSWERS),
        answers_dir / "part-00000.parquet",
    )

    snap = paths.snapshot_dir("snap1")
    snap.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                _comment(BASE + 1, author="author_a"),
                _comment(BASE + 11, parent_id=BASE + 1, time=1100,
                         author="author_x"),
            ],
            schema=contracts.COMMENTS,
        ),
        snap / "comments.parquet",
    )

    combine_mod.combine(["r1", "r2"], "t3", "rc")
    out = paths.run_dir("rc")
    assert not (out / "answers").exists()

    # `cards verify` loads the combined run and finds two verifiable rows.
    args = cli.build_parser().parse_args(
        ["cards", "verify", "--cardset", "mini", "--version", "t3",
         "--run", "rc"]
    )
    args.func(args)
    est = json.loads(capsys.readouterr().out)
    assert est["command"] == "verify" and est["estimated_calls"] == 2

    # `cards replies` finds the one outside reply to a qualifying problem.
    args = cli.build_parser().parse_args(
        ["cards", "replies", "--run", "rc", "--version", "t3",
         "--snapshot", "snap1"]
    )
    args.func(args)
    est = json.loads(capsys.readouterr().out)
    assert est["command"] == "replies" and est["estimated_calls"] == 1


def test_combine_cli(runs_env, monkeypatch, capsys):
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    _write_run("r1", [_row(BASE + 1, "r1")], _pain((BASE + 1, "p1")))
    _write_run("r2", [_row(BASE + 2, "r2")], _pain((BASE + 2, "p2")))
    args = cli.build_parser().parse_args(
        ["cards", "combine", "--runs", "r1,r2", "--version", "t3",
         "--run", "rc"]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["run_id"] == "rc" and out["taxonomy_version"] == "t3"
    assert [s["run_id"] for s in out["source_runs"]] == ["r1", "r2"]
    rows = load_assignments(paths.run_dir("rc"), "t3").rows
    assert [r["comment_id"] for r in rows] == [BASE + 1, BASE + 2]
    assert all(r["run_id"] == "rc" for r in rows)
    # The CLI is Jev-free: no transport, key, or cardset is needed.
    assert cards_cli is not None

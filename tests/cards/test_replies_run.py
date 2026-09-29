"""L23 task 23.4: `cards replies` — the unsolved-replies check over an
assignment run, on the mock transport only.

Problems are assigned comments with a real card at card_p >= 0.5 (optionally
limited to the top `--top-cards` cards). Replies come from the snapshot; the
run writes <run>/replies/{answers,mapping.parquet,unsolved_by_problem.parquet}
and resumes on rerun.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.cards import replies_run
from atlas.cards.engine import cli as cards_cli
from atlas.inference import keys
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[2]
BASE = 9_500_000_000
SNAP = "snap-replies"
RUN = "assign-r1"


def _comment(cid, **over):
    row = {f.name: None for f in contracts.COMMENTS}
    row.update(id=cid, time=1000, text_norm="synthetic text", state="ok")
    row.update(over)
    return row


def _assignment(cid, card_id, card_p, group_id="g01"):
    row = {f.name: None for f in contracts.ASSIGNMENTS}
    row.update(
        run_id=RUN,
        comment_id=cid,
        taxonomy_version="t0",
        group_id=group_id,
        card_id=card_id,
        card_p=card_p,
    )
    return row


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Assignment run + snapshot; paths pointed at tmp_path."""
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    configs = tmp_path / "configs"
    configs.mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    monkeypatch.setattr(paths, "CONFIGS", configs)

    run_dir = paths.run_dir(RUN)
    run_dir.mkdir(parents=True)
    rows = [
        _assignment(BASE + 100, "c0001", 0.9),   # qualifies
        _assignment(BASE + 200, "c0002", 0.6),   # qualifies
        _assignment(BASE + 300, "none", None),   # no card
        _assignment(BASE + 400, "c0002", 0.3),   # below threshold
        _assignment(BASE + 500, "c0001", 0.8),   # qualifies; c0001 -> 2
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / "assignments-t0.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"comment_id": c, "pain_sentence": f"pain of {c}"}
                for c in (BASE + 100, BASE + 200, BASE + 300, BASE + 400,
                          BASE + 500)
            ],
            schema=cards_cli.PAIN_SCHEMA,
        ),
        run_dir / "pain.parquet",
    )

    comments = [
        _comment(BASE + 100, author="author_a"),
        _comment(BASE + 200, author="author_b"),
        _comment(BASE + 300, author="author_c"),
        _comment(BASE + 400, author="author_d"),
        _comment(BASE + 500, author="author_e"),
        # one outside reply to P100 and one author follow-up
        _comment(BASE + 111, parent_id=BASE + 100, time=1100,
                 author="author_x"),
        _comment(BASE + 112, parent_id=BASE + 100, time=1200,
                 author="author_a"),
        _comment(BASE + 211, parent_id=BASE + 200, time=1100,
                 author="author_y"),
        _comment(BASE + 311, parent_id=BASE + 300, time=1100,
                 author="author_z"),  # reply to a non-qualifying problem
    ]
    snap = paths.snapshot_dir(SNAP)
    snap.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(comments, schema=contracts.COMMENTS),
        snap / "comments.parquet",
    )
    return tmp_path


def _chooser(state, qid, options):
    if qid == "author_says_solved":
        return "still_unsolved"
    if qid == "solution_kind":
        return "open_source_tool"
    return options[0]


def _noul(state, qid):
    # P100's reply names nothing; P200's reply names a tool.
    return 0.1 if state["problem"] == f"pain of {BASE + 100}" else 0.9


def _env(tmp_path, monkeypatch, seen):
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(
        cards_cli, "_transport",
        lambda: make_transport(chooser=_chooser, noul=_noul, seen=seen),
    )


def _args(*extra):
    return cli.build_parser().parse_args(
        ["cards", "replies", "--run", RUN, "--version", "t0",
         "--snapshot", SNAP, *extra]
    )


def test_selected_problems_threshold_and_top_cards(world):
    from atlas.cards.engine.assign import load_assignments

    rows = load_assignments(paths.run_dir(RUN), "t0").rows
    ids = replies_run.selected_problems(rows)
    assert ids == [BASE + 100, BASE + 200, BASE + 500]
    top = replies_run.selected_problems(rows, top_cards=1)
    assert top == [BASE + 100, BASE + 500]  # c0001 wins with two assignments


def test_dry_run_prints_estimate_only(world, monkeypatch, capsys):
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(
        cards_cli, "_transport", lambda: pytest.fail("client")
    )
    args = _args()
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "replies" and out["budget"] == "replies"
    # 2 outside replies + 1 author follow-up on qualifying problems.
    assert out["estimated_calls"] == 3
    assert not (paths.run_dir(RUN) / "replies").exists()


def test_replies_run_writes_outputs(world, tmp_path, monkeypatch, capsys):
    seen = []
    _env(tmp_path, monkeypatch, seen)
    args = _args("--yes")
    args.func(args)
    capsys.readouterr()

    assert len(seen) == 3
    out_dir = paths.run_dir(RUN) / "replies"
    answers = pq.read_table(out_dir / "answers").to_pylist()
    assert {r["question_set"] for r in answers} == {
        "replies@1", "reply-followups@1"
    }
    mapping = {
        r["reply_id"]: r
        for r in pq.read_table(out_dir / "mapping.parquet").to_pylist()
    }
    assert mapping[BASE + 111]["problem_id"] == BASE + 100
    assert mapping[BASE + 111]["kind"] == "reply"
    assert mapping[BASE + 112]["kind"] == "followup"
    assert BASE + 311 not in mapping  # BASE+300 never qualified

    unsolved = {
        r["comment_id"]: r
        for r in pq.read_table(
            out_dir / "unsolved_by_problem.parquet"
        ).to_pylist()
    }
    assert set(unsolved) == {BASE + 100, BASE + 200}
    p100 = unsolved[BASE + 100]
    assert p100["unsolved"] is True and p100["solved_p"] == 0.0
    assert p100["author_says_solved"] == "still_unsolved"
    p200 = unsolved[BASE + 200]
    assert p200["unsolved"] is False and p200["solved_p"] == 1.0
    assert p200["solution_kinds"] == ["open_source_tool"]

    # Rerun resumes: the mock sees no new paid calls.
    args = _args("--yes")
    args.func(args)
    assert len(seen) == 3


def test_top_cards_limits_items(world, tmp_path, monkeypatch, capsys):
    seen = []
    _env(tmp_path, monkeypatch, seen)
    args = _args("--top-cards", "1", "--yes")
    args.func(args)
    capsys.readouterr()
    # Only c0001 problems (BASE+100, BASE+500); P200's reply never runs.
    assert len(seen) == 2
    mapping = pq.read_table(
        paths.run_dir(RUN) / "replies" / "mapping.parquet"
    ).to_pylist()
    assert {r["problem_id"] for r in mapping} == {BASE + 100}


def test_replies_accepts_rate_flags():
    args = _args("--rpm", "300", "--concurrency", "2")
    assert args.rpm == 300 and args.concurrency == 2

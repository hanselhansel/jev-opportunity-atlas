"""L31 task 31.1: a budget stop must fail loudly.

Every paid command runs against the mock transport under a budgets.toml whose
caps sit below the cost of one call. Each must exit non-zero, print a JSON
line ``{"stopped": "budget", "budget": <name>, "completed": <n>,
"remaining": <n>}`` to stderr, and never print or write a result that reads
as complete (no assignments parquet, no merge-<v>.json, no proposals list).
"""

import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.cards.engine import cli as cards_cli
from atlas.cards.engine.assign import assign
from atlas.cards.engine.cardset import load_cardset
from atlas.inference import keys, ratelimit
from atlas.inference.runner import BudgetStopped
from atlas.robustness import cli as robust_cli
from tests.cards.test_engine_support import CANARY, PRICE, make_ctx, make_transport
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    mock_env,
    pilot_repo,
)
from tests.screen.support import FakeClock, write_sample

ROOT = Path(__file__).resolve().parents[3]
BASE = 9_500_000_000

TINY_BUDGETS = """\
account_total = 25.00
smoke = 0.0000001
pilot = 0.0000001
screen = 0.0000001
facets = 0.0000001
assign = 0.0000001
merge_verify = 0.0000001
replies = 0.0000001
robustness = 0.0000001
autoresearch = 0.0000001
discovery = 0.0000001
worst_case_tokens_per_unknown_attempt = 8000
"""


def _configs(tmp_path, monkeypatch, card_files=()):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    (configs / "budgets.toml").write_text(TINY_BUDGETS, encoding="utf-8")
    (configs / "prices.toml").write_bytes(
        (ROOT / "configs" / "prices.toml").read_bytes()
    )
    for name in card_files:
        src = ROOT / "configs" / "cards" / name
        (configs / "cards" / name).write_bytes(src.read_bytes())
    monkeypatch.setattr(paths, "CONFIGS", configs)
    return configs


def _env(tmp_path, monkeypatch, transport, card_files=()):
    _configs(tmp_path, monkeypatch, card_files)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(cards_cli, "_transport", lambda: transport)


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def _stop_line(capsys):
    captured = capsys.readouterr()
    err_lines = captured.err.strip().splitlines()
    assert err_lines, "expected a stderr line"
    return json.loads(err_lines[-1]), captured.out


def _items_file(tmp_path, rows):
    path = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    return str(path)


def _item_row(cid, pain):
    return {
        "comment_id": cid,
        "pain_sentence": pain,
        "sentences": [pain],
    }


def _assign_items(tmp_path):
    return _items_file(
        tmp_path,
        [
            _item_row(9_000_000_501, "ci keeps failing"),
            _item_row(9_000_000_502, "invoices by hand"),
            _item_row(9_000_000_503, "unmatched pain"),
        ],
    )


def _assignment(cid, card_id="c0001", card_p=0.9, group_id="g01", version="t0"):
    row = {f.name: None for f in contracts.ASSIGNMENTS}
    row.update(
        run_id="rb",
        comment_id=cid,
        taxonomy_version=version,
        group_id=group_id,
        card_id=card_id,
        card_p=card_p,
    )
    return row


def _write_run(run_dir, rows, version="t0"):
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / f"assignments-{version}.parquet",
    )
    pain = [
        {"comment_id": r["comment_id"], "pain_sentence": f"pain {r['comment_id']}"}
        for r in rows
    ]
    pq.write_table(
        pa.Table.from_pylist(pain, schema=cards_cli.PAIN_SCHEMA),
        run_dir / "pain.parquet",
    )


def test_assign_budget_stop(tmp_path, monkeypatch, capsys):
    _env(
        tmp_path,
        monkeypatch,
        make_transport(),
        card_files=("example.t0.yaml",),
    )
    args = _parse(
        [
            "cards", "assign", "--cardset", "example", "--version", "t0",
            "--run", "r1", "--items", _assign_items(tmp_path), "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line == {
        "stopped": "budget",
        "budget": "assign",
        "completed": 0,
        "remaining": 3,
    }
    run_dir = paths.run_dir("r1")
    assert not (run_dir / "assignments-t0.parquet").exists()
    assert not (run_dir / "pain.parquet").exists()


def test_merge_budget_stop(tmp_path, monkeypatch, capsys):
    _env(
        tmp_path,
        monkeypatch,
        make_transport(),
        card_files=("example.t0.yaml",),
    )
    run_dir = paths.run_dir("r1")
    _write_run(run_dir, [_assignment(9_000_000_501)])
    args = _parse(
        [
            "cards", "merge", "--cardset", "example", "--version", "t0",
            "--run", "r1", "--all-pairs", "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, out = _stop_line(capsys)
    assert line == {
        "stopped": "budget",
        "budget": "merge_verify",
        "completed": 0,
        "remaining": 3,
    }
    # The old bug printed "[]"; nothing list-shaped may reach stdout.
    assert "[" not in out
    assert not (run_dir / "merge-t0.json").exists()


def test_verify_budget_stop(tmp_path, monkeypatch, capsys):
    _env(
        tmp_path,
        monkeypatch,
        make_transport(),
        card_files=("example.t0.yaml",),
    )
    run_dir = paths.run_dir("r1")
    rows = [
        _assignment(9_000_000_501),
        _assignment(9_000_000_502, card_id="c0003", group_id="g02"),
    ]
    _write_run(run_dir, rows)
    args = _parse(
        [
            "cards", "verify", "--cardset", "example", "--version", "t0",
            "--run", "r1", "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "merge_verify"
    assert line["completed"] == 0 and line["remaining"] == 2
    written = pq.read_table(run_dir / "assignments-t0.parquet").to_pylist()
    assert all(r["verified_p"] is None for r in written)


def test_planted_budget_stop(tmp_path, monkeypatch, capsys):
    _env(
        tmp_path,
        monkeypatch,
        make_transport(),
        card_files=("example.t0.yaml", "planted.v1.yaml"),
    )
    from atlas.cards.engine.planted import load_planted, planted_items

    n_items = len(planted_items(load_planted("v1")))
    args = _parse(
        [
            "cards", "planted", "--cardset", "example", "--version", "t0",
            "--run", "r1", "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "merge_verify"
    assert line["completed"] == 0 and line["remaining"] == n_items
    assert "recovery" not in out


MINI_BASE_YAML = """\
taxonomy_version: t2
groups:
  g1: {label: "Alpha needs"}
  g2: {label: "Beta needs"}
cards:
  - {card_id: a1, group_id: g1, statement: "alpha one need", status: approved}
  - {card_id: b1, group_id: g2, statement: "beta one need", status: approved}
"""

MINI_NEW_YAML = """\
taxonomy_version: t3
groups:
  g1: {label: "Alpha needs"}
  g2: {label: "Beta needs"}
cards:
  - {card_id: a1, group_id: g1, statement: "alpha one need", status: approved}
  - {card_id: b1, group_id: g2, statement: "beta one need", status: approved}
  - {card_id: a3, group_id: g1, statement: "alpha three need", status: approved}
"""


def test_induce_budget_stop(tmp_path, monkeypatch, capsys):
    _env(tmp_path, monkeypatch, make_transport())
    cards_dir = paths.CONFIGS / "cards"
    (cards_dir / "mini.t2.yaml").write_text(MINI_BASE_YAML, encoding="utf-8")
    (cards_dir / "mini.t3.yaml").write_text(MINI_NEW_YAML, encoding="utf-8")
    base_rows = [
        _assignment(9_000_000_601, card_id="a1", card_p=0.9,
                    group_id="g1", version="t2"),
        _assignment(9_000_000_602, card_id="none", card_p=1.0,
                    group_id="g1", version="t2"),
        _assignment(9_000_000_603, card_id="b1", card_p=0.3,
                    group_id="g2", version="t2"),
    ]
    _write_run(paths.run_dir("rb"), base_rows, version="t2")
    items = _items_file(
        tmp_path,
        [
            _item_row(9_000_000_601, "alpha one pain"),
            _item_row(9_000_000_602, "alpha three pain"),
            _item_row(9_000_000_603, "beta one pain"),
        ],
    )
    args = _parse(
        [
            "cards", "induce", "--base-run", "rb", "--base-version", "t2",
            "--cardset", "mini", "--version", "t3", "--run", "r3",
            "--items", items, "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "assign"
    assert line["completed"] == 0 and line["remaining"] == 2
    run_dir = paths.run_dir("r3")
    assert not (run_dir / "assignments-t3.parquet").exists()
    assert not (run_dir / "induce-t3.json").exists()


def _comment(cid, **over):
    row = {f.name: None for f in contracts.COMMENTS}
    row.update(id=cid, time=1000, text_norm="synthetic text", state="ok")
    row.update(over)
    return row


def test_replies_budget_stop(tmp_path, monkeypatch, capsys):
    _env(
        tmp_path,
        monkeypatch,
        make_transport(),
        card_files=("example.t0.yaml",),
    )
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    run_dir = paths.run_dir("r1")
    _write_run(run_dir, [_assignment(BASE + 100)])
    snap = paths.snapshot_dir("snap-b")
    snap.mkdir(parents=True, exist_ok=True)
    comments = [
        _comment(BASE + 100, author="author_a"),
        _comment(BASE + 111, parent_id=BASE + 100, time=1100,
                 author="author_x"),
        _comment(BASE + 112, parent_id=BASE + 100, time=1200,
                 author="author_a"),
    ]
    pq.write_table(
        pa.Table.from_pylist(comments, schema=contracts.COMMENTS),
        snap / "comments.parquet",
    )
    args = _parse(
        [
            "cards", "replies", "--run", "r1", "--version", "t0",
            "--snapshot", "snap-b", "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "replies"
    assert line["completed"] == 0 and line["remaining"] == 2
    assert not (run_dir / "replies" / "unsolved_by_problem.parquet").exists()
    assert not (run_dir / "replies" / "mapping.parquet").exists()


def test_robust_assign_paraphrase_budget_stop(tmp_path, monkeypatch, capsys):
    _env(
        tmp_path,
        monkeypatch,
        make_transport(),
        card_files=("example.t0.yaml", "paraphrases.v1.json"),
    )
    monkeypatch.setattr(
        robust_cli, "_transport", lambda: make_transport()
    )
    args = _parse(
        [
            "robust", "assign-paraphrase", "--cardset", "example",
            "--version", "t0", "--items",
            _items_file(
                tmp_path,
                [
                    _item_row(9_000_000_801, "ci keeps failing"),
                    _item_row(9_000_000_802, "invoices by hand"),
                ],
            ),
            "--run", "rp1", "--para", "1", "--yes",
        ]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "robustness"
    assert line["completed"] == 0 and line["remaining"] == 2
    assert not (paths.run_dir("rp1") / "assignments-t0.parquet").exists()


def _write_facets_sample(sample_id, ids):
    from atlas.facets.phase2 import PHASE2_SCHEMA

    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "comment_id": int(c),
            "story_id": 9_000_100_000,
            "stratum": "pain|L1|H1|ask",
            "half": "explore",
            "phase": "pos",
            "w1": 2.0,
            "p2": 0.5,
            "weight": 4.0,
            "firsthand_p": 0.9,
        }
        for c in ids
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=PHASE2_SCHEMA),
        paths.sample_path(sample_id),
    )
    (paths.SAMPLES / f"{sample_id}.json").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "seed": 7,
                "parent_run": "scr-1",
                "cutoff": 0.7,
                "n_pos": len(ids),
                "n_neg": 0,
                "snapshot_id": SNAPSHOT_ID,
                "design": "two-phase",
            },
            indent=1,
        )
        + "\n"
    )


def _snapshot_ids(n):
    comments = pq.read_table(
        paths.snapshot_dir(SNAPSHOT_ID) / "comments.parquet",
        columns=["id", "eligible"],
    )
    return sorted(r["id"] for r in comments.to_pylist() if r["eligible"])[:n]


def test_facets_run_budget_stop(pilot_repo, monkeypatch, capsys):  # noqa: F811
    (pilot_repo / "configs" / "budgets.toml").write_text(
        TINY_BUDGETS, encoding="utf-8"
    )
    ids = _snapshot_ids(10)
    _write_facets_sample("fac-b", ids)
    mock_env(monkeypatch, make_transport())
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)
    args = _parse(
        ["facets", "run", "--sample-id", "fac-b", "--run", "fac-b1", "--yes"]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "facets"
    assert line["completed"] == 0 and line["remaining"] == 10


def test_screen_run_budget_stop(pilot_repo, monkeypatch, capsys):  # noqa: F811
    (pilot_repo / "configs" / "budgets.toml").write_text(
        TINY_BUDGETS, encoding="utf-8"
    )
    sid, _ids = write_sample("scr-b", n=10)
    mock_env(monkeypatch, make_transport())
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)
    args = _parse(
        ["screen", "run", "--sample", sid, "--run", "scr-b1", "--yes"]
    )
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    line, _out = _stop_line(capsys)
    assert line["stopped"] == "budget" and line["budget"] == "screen"
    assert line["completed"] == 0 and line["remaining"] == 2


def test_assign_level2_stop_counts_completed(tmp_path):
    """A cap that fits both group calls and one card call: BudgetStopped
    reports the level-2 stop with level-1 calls counted as completed."""
    import asyncio

    from atlas.cards.engine.assign import card_item, group_item
    from atlas.inference.questions import canonical_json

    cs = load_cardset("example", "t0")

    def est_tokens(item):
        body = {
            "state": item["state"],
            "model": "jev-1.13.0",
            "questions": item["questions"],
        }
        return math.ceil(len(canonical_json(body).encode("utf-8")) / 3.2)

    rows = [
        _item_row(9_000_000_501, "ci keeps failing"),
        _item_row(9_000_000_502, "invoices by hand"),
    ]
    g_est = [
        est_tokens(
            group_item(r["comment_id"], r["pain_sentence"], r["sentences"], cs)
        )
        for r in rows
    ]
    c_est = [
        est_tokens(
            card_item(r["comment_id"], r["pain_sentence"], r["sentences"],
                      cs, "g01")
        )
        for r in rows
    ]
    # Sequential calls (concurrency=1). Every send settles at the mock's 300
    # input tokens, so committed spend runs 0 -> g1 -> 300 -> g2 -> 600 ->
    # c1 -> 900. The cap must fit everything through the first card call and
    # reject the second card reserve.
    cap_tokens = 600 + c_est[0] + 0.01
    assert cap_tokens >= g_est[0]
    assert cap_tokens >= 300 + g_est[1]
    assert cap_tokens >= 600 + c_est[0]
    assert cap_tokens < 900 + c_est[1]
    ctx = make_ctx(
        tmp_path,
        make_transport(
            chooser=lambda s, q, opts: (
                "g01" if q == "group" else "c0001"
            )
        ),
        cap=cap_tokens * PRICE,
    )
    ctx.concurrency = 1
    with pytest.raises(BudgetStopped) as ei:
        asyncio.run(assign(ctx, rows, cs))
    assert ei.value.completed == 3  # 2 group + 1 card
    assert ei.value.remaining == 1  # the second card-level call

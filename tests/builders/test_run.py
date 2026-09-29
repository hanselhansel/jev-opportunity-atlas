"""S6 task 2 tests: launch items, the assign run, and the budget stop."""

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.builders import cli as builders_cli
from atlas.builders import run as builders_run
from atlas.builders import sample
from atlas.inference import keys
from tests.builders.test_sample import (
    BASE,
    SNAPSHOT_ID,
    month_ts,
    repo_paths,
    story_row,
)
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[2]

TINY_BUDGETS = """\
account_total = 25.00
builders = 0.0000001
worst_case_tokens_per_unknown_attempt = 8000
"""


def _configs(tmp_path, monkeypatch, budgets=None):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    if budgets is None:
        shutil.copy(ROOT / "configs" / "budgets.toml", configs)
    else:
        (configs / "budgets.toml").write_text(budgets, encoding="utf-8")
    shutil.copy(ROOT / "configs" / "prices.toml", configs)
    shutil.copy(
        ROOT / "configs" / "cards" / "example.t0.yaml",
        configs / "cards" / "example.t0.yaml",
    )
    monkeypatch.setattr(paths, "CONFIGS", configs)


def _env(tmp_path, monkeypatch, transport, budgets=None):
    _configs(tmp_path, monkeypatch, budgets=budgets)
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(builders_cli, "_transport", lambda: transport)


def _sample_table(ids, periods, weights):
    return pa.table(
        {
            "story_id": pa.array(ids, type=pa.int64()),
            "period": pa.array(periods, type=pa.string()),
            "weight": pa.array(weights, type=pa.float64()),
        },
        schema=sample.SAMPLE_SCHEMA,
    )


def _fixture_stories():
    return [
        story_row(
            BASE + 1,
            month_ts(1),
            "Show HN: Acme deployer",
            "First bit of body. Second sentence here! Third one too? "
            "A fourth that is cut.",
        ),
        story_row(BASE + 2, month_ts(1), "show hn: beta tool", ""),
        story_row(BASE + 3, month_ts(2), "Show HN: gamma", "Body text."),
    ]


def test_launch_items(tmp_path, monkeypatch):
    repo_paths(tmp_path, monkeypatch, _fixture_stories())
    ids = [BASE + 1, BASE + 2, BASE + 3]
    table = _sample_table(ids, ["P01", "P01", "P02"], [2.0, 2.0, 4.0])
    items = builders_run.launch_items(table, SNAPSHOT_ID)
    assert [it["comment_id"] for it in items] == ids
    first = items[0]
    assert first["pain_sentence"] == "Acme deployer"
    assert first["sentences"][0] == "Show HN: Acme deployer"
    assert first["sentences"][1:] == [
        "First bit of body.",
        "Second sentence here!",
        "Third one too?",
    ]
    assert items[1]["pain_sentence"] == "beta tool"
    assert items[1]["sentences"] == ["show hn: beta tool"]
    for it in items:
        assert sum(len(s) for s in it["sentences"]) <= 300


def test_launch_items_long_text_capped(tmp_path, monkeypatch):
    long_text = " ".join(["word"] * 200)
    rows = [
        story_row(BASE + 1, month_ts(1), "Show HN: cap check", long_text),
        story_row(BASE + 2, month_ts(1), "Show HN: " + "t" * 400, ""),
    ]
    repo_paths(tmp_path, monkeypatch, rows)
    table = _sample_table([BASE + 1, BASE + 2], ["P01", "P01"], [1.0, 1.0])
    items = builders_run.launch_items(table, SNAPSHOT_ID)
    for it in items:
        assert sum(len(s) for s in it["sentences"]) <= 300
    assert items[1]["pain_sentence"] == "t" * 400


def test_launch_items_unknown_story_raises(tmp_path, monkeypatch):
    repo_paths(tmp_path, monkeypatch, _fixture_stories())
    table = _sample_table([BASE + 99], ["P01"], [1.0])
    with pytest.raises(KeyError):
        builders_run.launch_items(table, SNAPSHOT_ID)


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def _draw_and_run(tmp_path, monkeypatch, transport, seed=5, budgets=None):
    stories = _fixture_stories()
    repo_paths(tmp_path, monkeypatch, stories)
    _env(tmp_path, monkeypatch, transport, budgets=budgets)
    table = sample.draw_launches(SNAPSHOT_ID, n=3, seed=seed)
    assert table.num_rows == 3
    args = _parse(
        [
            "builders",
            "run",
            "--cardset",
            "example",
            "--version",
            "t0",
            "--run",
            f"builders-{seed}",
            "--snapshot",
            SNAPSHOT_ID,
            "--yes",
        ]
    )
    return args


def test_uses_launch_instructions(tmp_path, monkeypatch, capsys):
    seen = []
    args = _draw_and_run(tmp_path, monkeypatch, make_transport(seen=seen))
    capsys.readouterr()  # drop the estimate line
    args.func(args)
    bodies = [json.loads(r.content) for r in seen]
    group = [b for b in bodies if "group" in b["questions"]]
    card = [b for b in bodies if "card" in b["questions"]]
    assert len(group) == 3 and card  # level 2 runs for non-none groups
    assert all(
        b["questions"]["group"]["instructions"]
        == builders_run.GROUP_INSTRUCTIONS
        for b in group
    )
    assert all(
        b["questions"]["card"]["instructions"]
        == builders_run.CARD_INSTRUCTIONS
        for b in card
    )
    problems = {b["state"]["problem"] for b in group}
    assert problems == {"Acme deployer", "beta tool", "gamma"}
    labels = {
        json.loads(line)["question_set"]
        for line in (paths.run_dir("builders-5") / "done.jsonl")
        .read_text()
        .splitlines()
    }
    assert labels == {"builders-g@t0", "builders-c@t0"}
    written = pq.read_table(
        paths.run_dir("builders-5") / "assignments-t0.parquet"
    ).to_pylist()
    assert len(written) == 3
    assert all(r["run_id"] == "builders-5" for r in written)


def test_budget_stop_exits_nonzero(tmp_path, monkeypatch, capsys):
    args = _draw_and_run(
        tmp_path, monkeypatch, make_transport(), budgets=TINY_BUDGETS
    )
    capsys.readouterr()
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    err = capsys.readouterr().err.strip().splitlines()
    line = json.loads(err[-1])
    assert line["stopped"] == "budget" and line["budget"] == "builders"
    assert line["completed"] == 0 and line["remaining"] == 3
    run_dir = paths.run_dir("builders-5")
    assert not (run_dir / "assignments-t0.parquet").exists()


def test_run_without_yes_only_estimates(tmp_path, monkeypatch, capsys):
    stories = _fixture_stories()
    repo_paths(tmp_path, monkeypatch, stories)
    _env(tmp_path, monkeypatch, make_transport())
    sample.draw_launches(SNAPSHOT_ID, n=3, seed=5)
    args = _parse(
        [
            "builders",
            "run",
            "--cardset",
            "example",
            "--version",
            "t0",
            "--run",
            "builders-5",
            "--snapshot",
            SNAPSHOT_ID,
        ]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "builders"
    assert out["budget"] == "builders"
    assert not paths.run_dir("builders-5").exists()


def test_draw_cli(tmp_path, monkeypatch, capsys):
    repo_paths(tmp_path, monkeypatch, _fixture_stories())
    _configs(tmp_path, monkeypatch)
    args = _parse(
        [
            "builders",
            "draw",
            "--n",
            "2",
            "--seed",
            "5",
            "--snapshot",
            SNAPSHOT_ID,
        ]
    )
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["sample_id"] == "builders-5" and out["n"] == 2
    assert Path(out["path"]).exists()


def test_story_section_merges(tmp_path, monkeypatch):
    """`story data --with builders` via a fake atlas.story.io and fake
    complaint replicates."""
    io_calls = []

    class FakeIo:
        @staticmethod
        def merge_section(path, key, value):
            io_calls.append((key, value))
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            data[key] = value
            Path(path).write_text(
                json.dumps(data, indent=1) + "\n", encoding="utf-8"
            )

    monkeypatch.setattr(builders_cli, "_story_io", lambda: FakeIo)
    monkeypatch.setattr(
        builders_cli,
        "_complaint_reps",
        lambda args, card_ids: {
            c: {"est": 0.1, "reps": [0.1] * 10} for c in card_ids
        },
    )
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "data" / "samples")
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    ids = [BASE + 1, BASE + 2]
    pq.write_table(
        _sample_table(ids, ["P01", "P01"], [1.0, 1.0]),
        paths.sample_path("builders-5"),
    )
    run_dir = paths.run_dir("builders-5")
    run_dir.mkdir(parents=True)
    rows = []
    for i, sid in enumerate(ids):
        row = {f.name: None for f in contracts.ASSIGNMENTS}
        row.update(
            run_id="builders-5",
            comment_id=sid,
            taxonomy_version="t0",
            group_id="g01",
            card_id="c0001" if i == 0 else "none",
            card_p=0.9,
        )
        rows.append(row)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / "assignments-t0.parquet",
    )
    (run_dir / "builders.json").write_text(
        json.dumps({"sample_id": "builders-5", "version": "t0"}) + "\n"
    )
    story_path = tmp_path / "story.json"
    story_path.write_text(
        json.dumps({"cards": [{"id": "c0001"}, {"id": "c0002"}]}) + "\n"
    )

    class Args:
        builders_run = "builders-5"

    builders_cli.story_section(Args(), story_path)
    data = json.loads(story_path.read_text())
    assert data["builders"]["n_sampled"] == 2
    assert data["builders"]["n_population"] == 2
    assert data["builders"]["match_rate"]["est"] == pytest.approx(0.5)
    by_card = {c["id"]: c["builders"] for c in data["cards"]}
    assert by_card["c0001"]["launch_share"]["est"] == pytest.approx(0.5)
    assert by_card["c0001"]["ratio"]["est"] == pytest.approx(5.0)
    assert by_card["c0002"]["launch_share"]["est"] == 0.0
    assert {k for k, _v in io_calls} == {"builders", "cards"}

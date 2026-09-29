"""S5 task 2: `solutions run` — Jev confirms reply-side tool mentions only.

A mention inside a problem comment counts as a complaint with no Jev call;
a mention inside a reply or author follow-up becomes one runner item per
(reply, tool) pair, confirmed when `recommends` noul >= 0.5. Outputs land in
<assign run>/solutions/{mentions.parquet, answers/, tallies.json} and reruns
resume through the runner's done set.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.cards.engine.combine import PAIN_SCHEMA
from atlas.inference import keys
from atlas.solutions import cli as sol_cli
from atlas.solutions import confirm
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[2]
BASE = 9_500_000_000
SNAP = "snap-tools"
RUN = "assign-tools"

TOOLS_YAML = """\
version: v1
tools:
  - {name: AWS, aliases: [aws, amazon web services], category: cloud_infra}
  - {name: Go, aliases: [golang], category: dev_tool}
  - {name: Cursor, aliases: [cursor ide], category: ai_coding}
  - {name: Deno, aliases: [deno], category: dev_tool}
"""


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
    """Assign run + snapshot + mini tools file; paths pointed at tmp_path."""
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    configs = tmp_path / "configs"
    configs.mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    (configs / "tools.v1.yaml").write_text(TOOLS_YAML, encoding="utf-8")
    monkeypatch.setattr(paths, "CONFIGS", configs)

    run_dir = paths.run_dir(RUN)
    run_dir.mkdir(parents=True)
    rows = [
        _assignment(BASE + 100, "c0001", 0.9),
        _assignment(BASE + 200, "c0002", 0.8),
        _assignment(BASE + 300, "c0002", 0.7),
        _assignment(BASE + 400, "none", None),
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / "assignments-t0.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"comment_id": c, "pain_sentence": f"pain of {c}"}
                for c in (BASE + 100, BASE + 200, BASE + 300, BASE + 400)
            ],
            schema=PAIN_SCHEMA,
        ),
        run_dir / "pain.parquet",
    )

    s1, s2, s3 = BASE + 10, BASE + 20, BASE + 30
    comments = [
        _comment(BASE + 100, author="author_a", story_id=s1,
                 text_norm="AWS costs keep spiking for us"),
        _comment(BASE + 200, author="author_b", story_id=s2,
                 text_norm="nothing fits our workflow"),
        _comment(BASE + 300, author="author_c", story_id=s3,
                 text_norm="Cursor ate my files twice"),
        _comment(BASE + 400, author="author_d", story_id=BASE + 40,
                 text_norm="AWS again"),
        _comment(BASE + 111, parent_id=BASE + 100, time=1100,
                 author="author_x", story_id=s1,
                 text_norm="switch to Go for cheaper workers"),
        _comment(BASE + 112, parent_id=BASE + 100, time=1200,
                 author="author_a", story_id=s1,
                 text_norm="ended up on AWS spot instead"),
        _comment(BASE + 211, parent_id=BASE + 200, time=1100,
                 author="author_y", story_id=s2,
                 text_norm="we run AWS lambda for this"),
        _comment(BASE + 311, parent_id=BASE + 300, time=1100,
                 author="author_z", story_id=s3,
                 text_norm="try Deno instead"),
    ]
    snap = paths.snapshot_dir(SNAP)
    snap.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(comments, schema=contracts.COMMENTS),
        snap / "comments.parquet",
    )
    return tmp_path


def _env(monkeypatch, seen):
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))

    def noul(state, qid):
        # Deno is never recommended; every other confirm passes.
        return 0.1 if state["tool"] == "Deno" else 0.9

    monkeypatch.setattr(
        sol_cli, "_transport", lambda: make_transport(noul=noul, seen=seen)
    )


def _args(*extra):
    return cli.build_parser().parse_args(
        ["solutions", "run", "--assign-run", RUN, "--snapshot", SNAP, *extra]
    )


def test_confirm_items_shape():
    hits = [
        {
            "comment_id": BASE + 111,
            "problem_id": BASE + 100,
            "tool": "Go",
            "text": "x" * 5000,
            "pain": "deploys keep breaking",
        }
    ]
    items = confirm.confirm_items(hits)
    assert len(items) == 1
    it = items[0]
    assert it["reply_id"] == BASE + 111
    assert set(it["state"]) == {"problem", "reply", "tool"}
    assert it["state"]["problem"] == "deploys keep breaking"
    assert len(it["state"]["reply"]) == 1200
    assert it["state"]["tool"] == "Go"
    assert list(it["questions"]) == ["recommends"]
    assert it["questions"]["recommends"]["type"] == "noul"


def test_confirm_items_distinct_ids_per_tool():
    hits = [
        {"comment_id": BASE + 111, "problem_id": BASE + 100, "tool": "Go",
         "text": "a", "pain": "p"},
        {"comment_id": BASE + 111, "problem_id": BASE + 100, "tool": "AWS",
         "text": "a", "pain": "p"},
    ]
    items = confirm.confirm_items(hits)
    assert items[0]["comment_id"] != items[1]["comment_id"]


def test_dry_run_prints_estimate_only(world, monkeypatch, capsys):
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(
        sol_cli, "_transport", lambda: pytest.fail("client")
    )
    args = _args()
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "solutions" and out["budget"] == "solutions"
    # 4 reply-kind hits: R111/Go, F112/AWS, R211/AWS, R311/Deno.
    assert out["estimated_calls"] == 4
    assert not (paths.run_dir(RUN) / "solutions").exists()


def test_problem_mention_is_complaint_no_call(world, monkeypatch, capsys):
    seen = []
    _env(monkeypatch, seen)
    args = _args("--yes")
    args.func(args)
    capsys.readouterr()
    # Problem-side mentions (AWS on P100, Cursor on P300, AWS on P400's
    # unassigned problem) place no call: only the 4 reply-kind hits do.
    assert len(seen) == 4
    bodies = [json.loads(r.content) for r in seen]
    tools = sorted(b["state"]["tool"] for b in bodies)
    assert tools == ["AWS", "AWS", "Deno", "Go"]
    assert all(set(b["state"]) == {"problem", "reply", "tool"} for b in bodies)


def test_tallies_and_resume(world, monkeypatch, capsys):
    seen = []
    _env(monkeypatch, seen)
    args = _args("--yes")
    args.func(args)
    capsys.readouterr()

    out_dir = paths.run_dir(RUN) / "solutions"
    tallies = json.loads((out_dir / "tallies.json").read_text())
    tools = {t["name"]: t for t in tallies["tools"]}

    aws = tools["AWS"]
    assert aws["category"] == "cloud_infra"
    assert aws["complaint_threads"] == 1  # S1 problem comment
    assert aws["fix_threads"] == 2  # S1 follow-up + S2 reply, confirmed
    assert aws["threads"] == 2
    assert abs(aws["fix_share"]["est"] - 2 / 3) < 1e-9
    assert aws["fix_share"]["lo95"] <= aws["fix_share"]["est"]
    assert aws["fix_share"]["hi95"] >= aws["fix_share"]["est"]
    assert aws["sparse"] is True

    cur = tools["Cursor"]
    assert cur["complaint_threads"] == 1 and cur["fix_threads"] == 0
    assert cur["fix_share"]["est"] == 0.0

    go = tools["Go"]
    assert go["fix_threads"] == 1 and go["complaint_threads"] == 0
    assert go["fix_share"]["est"] == 1.0

    deno = tools["Deno"]  # named in a reply but never confirmed
    assert deno["threads"] == 0 and deno["fix_share"] is None
    assert deno["sparse"] is True

    cards = tallies["cards_tools"]
    assert {f["name"] for f in cards["c0001"]["fixes"]} == {"Go", "AWS"}
    assert {b["name"] for b in cards["c0001"]["blamed"]} == {"AWS"}
    assert {f["name"] for f in cards["c0002"]["fixes"]} == {"AWS"}
    assert {b["name"] for b in cards["c0002"]["blamed"]} == {"Cursor"}

    mentions = pq.read_table(out_dir / "mentions.parquet").to_pylist()
    assert not any(
        key in mentions[0] for key in ("text", "pain", "stratum")
    )
    kinds = {(r["kind"], r["tool"]) for r in mentions}
    assert ("problem", "Cursor") in kinds and ("followup", "AWS") in kinds

    # Rerun resumes: no new paid calls.
    args = _args("--yes")
    args.func(args)
    assert len(seen) == 4


def test_rerun_resumes_no_duplicate_calls(world, monkeypatch, capsys):
    seen = []
    _env(monkeypatch, seen)
    args = _args("--yes")
    args.func(args)
    args = _args("--yes")
    args.func(args)
    capsys.readouterr()
    assert len(seen) == 4


def test_budget_stop_exits_nonzero(world, monkeypatch, capsys):
    configs = paths.CONFIGS
    (configs / "budgets.toml").write_text(
        "account_total = 25.0\n"
        "solutions = 0.0000001\n"
        "worst_case_tokens_per_unknown_attempt = 8000\n",
        encoding="utf-8",
    )
    _env(monkeypatch, [])
    args = _args("--yes")
    with pytest.raises(SystemExit) as ei:
        args.func(args)
    assert ei.value.code != 0
    err = capsys.readouterr().err.strip().splitlines()[-1]
    line = json.loads(err)
    assert line["stopped"] == "budget" and line["budget"] == "solutions"
    assert not (paths.run_dir(RUN) / "solutions" / "tallies.json").exists()


def test_solutions_accepts_rate_flags():
    args = _args("--rpm", "300", "--concurrency", "2")
    assert args.rpm == 300 and args.concurrency == 2

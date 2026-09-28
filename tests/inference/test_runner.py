"""Batch runner: dispatch, ledger rows, budget stop, cache replays, parts."""

import asyncio
import json

import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient, RetryPolicy
from atlas.inference.ledger import read_rows, summarize
from atlas.inference.questions import load_question_set
from atlas.inference.runner import RunContext, run_batch
from atlas.inference.runner_io import write_part
from tests.inference.mock_jev import make_transport

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64
PRICE = 0.042e-6


def items(n):
    return [{"comment_id": i, "comment": f"text {i}", "parent": "", "story_title": "T",
             "thread_type": "story", "sentences": [f"text {i}"]} for i in range(n)]


def ctx(tmp_path, script, cap=1.0, on_request=None, concurrency=4):
    client = JevClient(api_key=CANARY, base="http://mock", transport=make_transport(script, on_request=on_request),
                       policy=RetryPolicy(backoff_initial=0, backoff_max=0))
    guard = BudgetGuard(cap_usd=cap, usd_per_input_token=PRICE, worst_case_tokens_unknown=8000)
    return RunContext(run_id="r1", run_dir=tmp_path / "r1", client=client, guard=guard,
                      model="jev-1.13.0", price_version="typesafe-2026-09-28",
                      cache_path=tmp_path / "cache.sqlite", concurrency=concurrency)


def answer_row(**over):
    base = {f.name: None for f in contracts.ANSWERS}
    base.update(run_id="r1", comment_id=1, question_set="screen@0", question_id="q",
                qtype="noul", cache_hit=False)
    base.update(over)
    return base


def test_runs_all_items_and_writes_answers(tmp_path):
    qs = load_question_set("screen", 0)
    out = asyncio.run(run_batch(ctx(tmp_path, []), items(5), qs))
    assert out["completed"] == 5 and out["failed"] == 0
    table = pq.read_table(tmp_path / "r1" / "answers")
    assert table.num_rows == 5 * len(qs.questions)


def test_resume_skips_completed_and_second_run_is_all_replays(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(3), qs))
    again = asyncio.run(run_batch(ctx(tmp_path, []), items(5), qs))
    assert again["skipped_completed"] == 3 and again["completed"] == 2
    other_run = ctx(tmp_path, [])
    other_run.run_id, other_run.run_dir = "r2", tmp_path / "r2"
    replay = asyncio.run(run_batch(other_run, items(5), qs))
    assert replay["cache_hits"] == 5 and replay["new_requests"] == 0


def test_budget_stop_is_clean_and_resumable(tmp_path):
    qs = load_question_set("screen", 0)
    out = asyncio.run(run_batch(ctx(tmp_path, [], cap=0.00005), items(20), qs))
    assert out["stopped"] == "budget" and 0 < out["completed"] < 20


def test_guard_counts_retry_attempts_live(tmp_path):
    qs = load_question_set("screen", 0)
    snapshot = []

    def on_request(n, _request):
        if n == 3:
            snapshot.append((c.guard.unknown_attempts, c.guard.committed_usd))

    c = ctx(tmp_path, ["500", "timeout", "ok"], on_request=on_request, concurrency=1)
    out = asyncio.run(run_batch(c, items(1), qs))
    assert out["completed"] == 1
    assert snapshot and snapshot[0][0] == 2
    assert snapshot[0][1] >= 2 * 8000 * PRICE
    assert c.guard.unknown_attempts == 2
    s = summarize(tmp_path / "r1" / "ledger.jsonl")
    assert s["attempts"] == 3 and s["unknown_attempts"] == 2


def test_answer_parts_never_overwritten(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(3), qs))
    part1 = tmp_path / "r1" / "answers" / "part-1.parquet"
    original_bytes = part1.read_bytes()
    out = asyncio.run(run_batch(ctx(tmp_path, []), items(6), qs))
    assert out["skipped_completed"] == 3
    part2 = tmp_path / "r1" / "answers" / "part-2.parquet"
    assert part2.exists() and part1.read_bytes() == original_bytes


def test_write_part_assigns_increasing_seqs(tmp_path):
    run_dir = tmp_path / "r9"
    run_dir.mkdir()
    assert write_part(run_dir, [answer_row()]) == 1
    assert write_part(run_dir, [answer_row(comment_id=2)]) == 2
    assert sorted(p.name for p in (run_dir / "answers").iterdir()) == [
        "part-1.parquet",
        "part-2.parquet",
    ]


def test_items_consumed_lazily(tmp_path):
    qs = load_question_set("screen", 0)
    pulls = []

    def gen():
        for i in range(5):
            pulls.append(i)
            yield {"comment_id": i, "comment": f"text {i}", "parent": "", "story_title": "T",
                   "thread_type": "story", "sentences": [f"text {i}"]}

    at_first_request = []

    def on_request(n, _request):
        if n == 1:
            at_first_request.append(len(pulls))

    c = ctx(tmp_path, [], on_request=on_request)
    c.batch_items = 2
    asyncio.run(run_batch(c, gen(), qs))
    assert at_first_request and at_first_request[0] <= 2
    assert len(list((tmp_path / "r1" / "answers").glob("part-*.parquet"))) == 3


def test_replay_rows_are_not_attempts(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(5), qs))
    c = ctx(tmp_path, [])
    c.run_id, c.run_dir = "r2", tmp_path / "r2"
    asyncio.run(run_batch(c, items(5), qs))
    s = summarize(tmp_path / "r2" / "ledger.jsonl")
    assert s["attempts"] == 0 and s["replays"] == 5
    rows = read_rows(tmp_path / "r2" / "ledger.jsonl")
    assert all(r["attempt"] == 0 for r in rows)


def test_no_key_in_run_artifacts(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, ["500", "ok"]), items(1), qs))
    assert CANARY not in (tmp_path / "r1" / "ledger.jsonl").read_text()
    assert CANARY not in (tmp_path / "r1" / "run_manifest.json").read_text()
    assert CANARY not in (tmp_path / "r1" / "done.jsonl").read_text()
    assert CANARY.encode() not in (tmp_path / "cache.sqlite").read_bytes()


def test_cumulative_budget_through_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    qs = load_question_set("screen", 0)
    guard_a = BudgetGuard.for_budget("pilot", cap_usd=1.0, usd_per_input_token=PRICE,
                                     worst_case_tokens_unknown=8000)
    client = JevClient(api_key=CANARY, base="http://mock", transport=make_transport([]),
                       policy=RetryPolicy(backoff_initial=0, backoff_max=0))
    c = RunContext(run_id="A", client=client, guard=guard_a, model="jev-1.13.0",
                   price_version="typesafe-2026-09-28", run_dir=paths.run_dir("A"),
                   cache_path=tmp_path / "cache.sqlite", concurrency=1, budget="pilot")
    asyncio.run(run_batch(c, items(2), qs))
    guard_a.close()
    spent = summarize(paths.run_dir("A") / "ledger.jsonl")["calculated_usd"]
    assert spent > 0
    guard_b = BudgetGuard.for_budget("pilot", cap_usd=1.0, usd_per_input_token=PRICE,
                                     worst_case_tokens_unknown=8000)
    try:
        assert guard_b.committed_usd == pytest.approx(spent)
    finally:
        guard_b.close()


def test_manifest_records_run_metadata(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(1), qs))
    manifest = json.loads((tmp_path / "r1" / "run_manifest.json").read_text())
    assert manifest["run_id"] == "r1" and manifest["model"] == "jev-1.13.0"
    assert manifest["question_sets"] == [{"label": "screen@0", "file_sha256": qs.sha256}]
    assert manifest["price_version"] == "typesafe-2026-09-28"
    assert manifest["cap_usd"] == 1.0

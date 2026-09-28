"""Runner resume semantics: crashes, dropped parts, several sets per run dir."""

import asyncio
import json

import pyarrow.parquet as pq
import pytest

from atlas.inference.client import ModelMismatch
from atlas.inference.ledger import read_rows, summarize, unresolved_pending
from atlas.inference.questions import load_question_set
from atlas.inference.runner import run_batch
from atlas.inference.runner_io import ManifestMismatch
from tests.inference.test_runner import ctx, items


def test_runner_crash_after_send_before_flush(tmp_path):
    qs = load_question_set("screen", 0)

    def crash_on_third(n, _request):
        if n == 3:
            raise RuntimeError("injected crash after send")

    with pytest.raises(RuntimeError, match="injected crash"):
        asyncio.run(run_batch(ctx(tmp_path, [], on_request=crash_on_third, concurrency=1), items(5), qs))
    assert not (tmp_path / "r1" / "answers").exists() or not list(
        (tmp_path / "r1" / "answers").glob("*")
    )
    assert len(unresolved_pending(read_rows(tmp_path / "r1" / "ledger.jsonl"))) == 1

    out = asyncio.run(run_batch(ctx(tmp_path, []), items(5), qs))
    assert out["completed"] == 5
    table = pq.read_table(tmp_path / "r1" / "answers")
    pairs = {(r["comment_id"], r["question_id"]) for r in table.to_pylist()}
    assert len(pairs) == 5 * len(qs.questions)
    rows = read_rows(tmp_path / "r1" / "ledger.jsonl")
    assert summarize(tmp_path / "r1" / "ledger.jsonl")["unknown_attempts"] == 1
    assert sum(1 for r in rows if r["cost_class"] == "unknown") == 1


def test_done_row_with_missing_part_is_redone(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(2), qs))
    (tmp_path / "r1" / "answers" / "part-1.parquet").unlink()
    out = asyncio.run(run_batch(ctx(tmp_path, []), items(2), qs))
    assert out["skipped_completed"] == 0
    assert out["completed"] == 2 and out["cache_hits"] == 2


def test_screen_then_deep_same_run_dir(tmp_path):
    asyncio.run(run_batch(ctx(tmp_path, []), items(2), load_question_set("screen", 0)))
    asyncio.run(run_batch(ctx(tmp_path, []), items(2), load_question_set("deep", 0)))
    manifest = json.loads((tmp_path / "r1" / "run_manifest.json").read_text())
    assert [e["label"] for e in manifest["question_sets"]] == ["screen@0", "deep@0"]
    done_labels = {
        json.loads(line)["question_set"]
        for line in (tmp_path / "r1" / "done.jsonl").read_text().splitlines()
        if line.strip()
    }
    assert done_labels == {"screen@0", "deep@0"}
    per_set = summarize(tmp_path / "r1" / "ledger.jsonl", by="question_set")["question_sets"]
    assert per_set["screen@0"]["calls"] == 2 and per_set["deep@0"]["calls"] == 2
    table = pq.read_table(tmp_path / "r1" / "answers")
    support = [
        r["choice"]
        for r in table.to_pylist()
        if r["question_id"] == "support_sentence"
    ]
    assert support == ["s0", "s0"]


def test_manifest_model_change_raises(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(1), qs))
    calls = []
    c = ctx(tmp_path, [], on_request=lambda n, _r: calls.append(n))
    c.model = "jev-9.9.9"
    with pytest.raises(ManifestMismatch):
        asyncio.run(run_batch(c, items(1), qs))
    assert calls == []


def test_manifest_question_set_hash_change_raises(tmp_path):
    qs = load_question_set("screen", 0)
    asyncio.run(run_batch(ctx(tmp_path, []), items(1), qs))
    manifest_path = tmp_path / "r1" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["question_sets"][0]["file_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    calls = []
    c = ctx(tmp_path, [], on_request=lambda n, _r: calls.append(n))
    with pytest.raises(ManifestMismatch):
        asyncio.run(run_batch(c, items(1), qs))
    assert calls == []


def test_model_mismatch_aborts_run(tmp_path):
    qs = load_question_set("screen", 0)
    with pytest.raises(ModelMismatch):
        asyncio.run(run_batch(ctx(tmp_path, ["wrong_model"], concurrency=1), items(2), qs))
    rows = read_rows(tmp_path / "r1" / "ledger.jsonl")
    finals = [r for r in rows if r["cost_class"] != "pending"]
    assert len(finals) == 1 and unresolved_pending(rows) == []
    assert finals[0]["validation"] == "schema"

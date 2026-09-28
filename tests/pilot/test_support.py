"""Shared helpers for pilot tests: a synthetic multi-stratum snapshot, a
tmp-path repo fixture with the real configs, and a text-aware Jev mock
transport.

The snapshot covers six v2 strata with very uneven sizes (~3000 down to 10)
plus an ineligible block, so both the pilot allocation formula and the
min_per_stratum floor are exercised. All ids are synthetic (>= 9_000_000_000).

The mock transport returns noul 0.9 when the text a question refers to
(state["comment"], or state["c{j}"] for packed "c{j}_*" questions) contains
"PAIN", else 0.1; the first option for choice; 1.0 for score. usage is
deterministic: input_tokens = len(request.content) // 4. `seen` collects
every request that reaches the handler.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from tests.inference.mock_jev import answer_for

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ID = "pilotsnap"
CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64

# (count, text_norm, word_count, period, thread_type) -> one v2 stratum each.
BLOCKS = (
    (
        3000,
        "PAIN: I spent three days on a manual workaround for our invoice flow.",
        40,
        "P01",
        "ask_hn",
    ),  # pain|L1|H1|ask
    (200, "Nice release notes for the update.", 8, "P08", "story"),
    # nopain|L0|H2|story
    (
        200,
        "PAIN: we wasted a week migrating off the old vendor; the new one keeps failing.",
        100,
        "P10",
        "show_hn",
    ),  # pain|L2|H2|show
    (12, "PAIN: my export broke.", 4, "P02", "ask_hn"),  # pain|L0|H1|ask
    (
        10,
        "A long detailed comment about product architecture tradeoffs.",
        220,
        "P03",
        "poll",
    ),  # nopain|L3|H1|other
    (15, "Short one.", 5, "P05", "tell_hn"),  # nopain|L0|H1|ask
)

EXPECTED_SIZES = {
    "pain|L1|H1|ask": 3000,
    "nopain|L0|H2|story": 200,
    "pain|L2|H2|show": 200,
    "pain|L0|H1|ask": 12,
    "nopain|L3|H1|other": 10,
    "nopain|L0|H1|ask": 15,
}


def write_snapshot(base: Path, snapshot_id: str = SNAPSHOT_ID) -> Path:
    """Write comments.parquet + stories.parquet for the BLOCKS fixture."""
    snap = Path(base) / snapshot_id
    snap.mkdir(parents=True, exist_ok=True)
    comments, stories = snapshot_tables()
    pq.write_table(comments, snap / "comments.parquet")
    pq.write_table(stories, snap / "stories.parquet")
    return snap


def snapshot_tables() -> tuple[pa.Table, pa.Table]:
    story_rows, comment_rows = [], []
    next_id = 9_000_000_001
    for i, (count, text, wc, period, ttype) in enumerate(BLOCKS):
        story_id = 9_000_100_000 + i
        story_rows.append(
            {
                "id": story_id,
                "thread_type": ttype,
                "title": f"Synthetic story {i}",
                "text_norm": f"Synthetic story text {i}.",
            }
        )
        for _ in range(count):
            # Unique text per comment so the response cache never replays.
            ctext = f"{text} ref {next_id}."
            comment_rows.append(
                {
                    "id": next_id,
                    "story_id": story_id,
                    "parent_id": story_id,
                    "period": period,
                    "thread_type": ttype,
                    "text_norm": ctext,
                    "sentences": [ctext],
                    "text_sha256": hashlib.sha256(ctext.encode()).hexdigest(),
                    "word_count": wc,
                    "eligible": True,
                }
            )
            next_id += 1
    # Ineligible rows must never enter the frame.
    for _ in range(25):
        text = "Deleted or off-topic filler."
        comment_rows.append(
            {
                "id": next_id,
                "story_id": 9_000_100_000,
                "parent_id": None,
                "period": "P04",
                "thread_type": "story",
                "text_norm": text,
                "sentences": [text],
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "word_count": 6,
                "eligible": False,
            }
        )
        next_id += 1
    comments = pa.table(
        {
            "id": pa.array(
                [r["id"] for r in comment_rows], type=pa.int64()
            ),
            "story_id": pa.array(
                [r["story_id"] for r in comment_rows], type=pa.int64()
            ),
            "parent_id": pa.array(
                [r["parent_id"] for r in comment_rows], type=pa.int64()
            ),
            "period": [r["period"] for r in comment_rows],
            "thread_type": [r["thread_type"] for r in comment_rows],
            "text_norm": [r["text_norm"] for r in comment_rows],
            "sentences": pa.array(
                [r["sentences"] for r in comment_rows],
                type=pa.list_(pa.string()),
            ),
            "text_sha256": [r["text_sha256"] for r in comment_rows],
            "word_count": pa.array(
                [r["word_count"] for r in comment_rows], type=pa.int32()
            ),
            "eligible": pa.array(
                [r["eligible"] for r in comment_rows], type=pa.bool_()
            ),
        }
    )
    stories = pa.table(
        {
            "id": pa.array([r["id"] for r in story_rows], type=pa.int64()),
            "thread_type": [r["thread_type"] for r in story_rows],
            "title": [r["title"] for r in story_rows],
            "text_norm": [r["text_norm"] for r in story_rows],
        }
    )
    return comments, stories


@pytest.fixture
def pilot_repo(tmp_path, monkeypatch):
    """Synthetic snapshot plus real configs under tmp_path; every paths.* root
    pointed at tmp_path so nothing writes into the real data/, runs/ dirs."""
    write_snapshot(tmp_path / "snapshots")
    configs = tmp_path / "configs"
    (configs / "questions").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml", "sampling_v2.toml"):
        shutil.copy(ROOT / "configs" / name, configs / name)
    for src in sorted((ROOT / "configs" / "questions").glob("*.json")):
        shutil.copy(src, configs / "questions" / src.name)
    injected = ROOT / "configs" / "pilot" / "injected_cases.json"
    if injected.exists():
        (configs / "pilot").mkdir(exist_ok=True)
        shutil.copy(injected, configs / "pilot" / injected.name)
    (configs / "acquisition.toml").write_text(f'snapshot_id = "{SNAPSHOT_ID}"\n')
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "data" / "samples")
    monkeypatch.setattr(paths, "LABELS", tmp_path / "data" / "labels")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "data" / "cache")
    monkeypatch.setattr(paths, "MANIFESTS", tmp_path / "manifests")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CONFIGS", configs)
    return tmp_path


def mock_env(monkeypatch, transport) -> None:
    """Canary key + mock base + stages._transport override."""
    from atlas.inference import keys
    from atlas.pilot import stages

    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(stages, "_transport", lambda: transport)


_SLOT = re.compile(r"^(c\d+)_")


def _slot_text(state: dict, qid: str) -> str:
    """Text a question refers to: slot key for packed ids, else `comment`."""
    m = _SLOT.match(qid)
    if m and m.group(1) in state:
        return str(state[m.group(1)])
    return str(state.get("comment") or "")


def make_transport(seen=None, noul=None) -> httpx.MockTransport:
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        if seen is not None:
            seen.append(request)
        body = json.loads(request.content)
        state = body.get("state") or {}
        answers = {}
        for qid, q in body.get("questions", {}).items():
            if q.get("type") == "noul":
                value = (
                    noul(state, qid)
                    if callable(noul)
                    else (0.9 if "PAIN" in _slot_text(state, qid) else 0.1)
                )
                answers[qid] = {"type": "noul", "noul": value}
            else:
                answers[qid] = answer_for(q)
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": f"req_{counter['n']:04d}"},
            json={
                "model": "jev-1.13.0",
                "answers": answers,
                "usage": {
                    "input_tokens": len(request.content) // 4,
                    "output_tokens": 8,
                },
            },
        )

    return httpx.MockTransport(handler)


def answers_table(rows, run_id="r1", question_set="screen@1") -> pa.Table:
    """(comment_id, question_id, noul) triples -> contract ANSWERS table."""
    base = {f.name: None for f in contracts.ANSWERS}
    records = []
    for i, (cid, qid, noul) in enumerate(rows):
        records.append(
            {
                **base,
                "run_id": run_id,
                "comment_id": cid,
                "question_set": question_set,
                "question_id": qid,
                "qtype": "noul",
                "noul": noul,
                "model_returned": "jev-1.13.0",
                "request_id": f"req-{i}",
                "logical_call_id": f"lc-{run_id}-{i}",
                "cache_hit": False,
            }
        )
    return pa.Table.from_pylist(records, schema=contracts.ANSWERS)


def ledger_row(
    comment_id,
    question_set,
    input_tokens,
    cost_class="calculated",
    run_id="r1",
):
    row = {k: None for k in contracts.LEDGER_FIELDS}
    row.update(
        run_id=run_id,
        logical_call_id=f"lc-{run_id}-{comment_id}-{question_set}",
        attempt=1,
        comment_id=comment_id,
        question_set=question_set,
        question_count=1,
        input_hash=f"h-{comment_id}",
        model_requested="jev-1.13.0",
        model_returned="jev-1.13.0",
        request_id=f"req-{comment_id}",
        started_at="2026-09-29T00:00:00Z",
        ended_at="2026-09-29T00:00:01Z",
        queue_ms=0.0,
        request_ms=100.0,
        backoff_ms=0.0,
        http_status=200,
        validation="ok",
        input_tokens=input_tokens,
        output_tokens=0,
        cache="miss",
        price_version="typesafe-2026-09-28",
        cost_usd=(
            input_tokens * 0.042e-6 if input_tokens is not None else None
        ),
        cost_class=cost_class,
    )
    return row


def write_ledger(path, rows) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_fixture_covers_the_six_strata(pilot_repo):
    import numpy as np

    from atlas.sampling import design_v2

    sdir = paths.snapshot_dir(SNAPSHOT_ID)
    comments = pq.read_table(sdir / "comments.parquet")
    stories = pq.read_table(sdir / "stories.parquet")
    frame = design_v2.build_frame_v2(comments, stories)
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(labels, return_counts=True)
    assert {str(u): int(c) for u, c in zip(uniq, counts)} == EXPECTED_SIZES
    assert frame.num_rows == sum(EXPECTED_SIZES.values())

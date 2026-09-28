# L3: Jev client, attempt ledger, budget guard, cache, batch runner

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l3-inference

**Goal:** Call TypeSafe Jev so that every network attempt is recorded, spend can never pass the cap, cached answers replay for free, and an interrupted run resumes without repeating completed calls.

**Architecture:** A thin async client posts to `POST {base}/v1/systemone` with httpx and runs its own retry loop (the TypeSafe SDK retries twice by default and would hide attempts). Every attempt becomes one ledger row with exactly `contracts.LEDGER_FIELDS`. A budget guard reserves estimated cost before dispatch and settles it after. A SQLite cache keyed by canonical request content returns saved responses as replays. A batch runner ties these together and writes `ANSWERS` Parquet parts.

**Tech Stack:** Python 3.11, httpx (MockTransport in tests), sqlite3, pyarrow, asyncio.

Read first: `AGENTS.md`, `src/atlas/contracts.py`, `configs/questions/*.v0.json`, `configs/prices.toml`, `configs/budgets.toml`, spec sections 5 and 8.

**Security rules for this lane (hard):**
- Never read macOS Keychain in tests. Tests set `TYPESAFE_API_KEY` to the canary built at runtime (`"apikey_" + "0"*36 + "_" + "f"*64`) and use `httpx.MockTransport`.
- The API key must never appear in a ledger row, exception message, log line, repr, or cache entry. Task 3.3 tests this.

**Files you own:**
- `src/atlas/inference/__init__.py`
- `src/atlas/inference/keys.py`
- `src/atlas/inference/questions.py`
- `src/atlas/inference/client.py`
- `src/atlas/inference/ledger.py`
- `src/atlas/inference/budget.py`
- `src/atlas/inference/cache.py`
- `src/atlas/inference/runner.py`
- `src/atlas/inference/cli.py` (`register(sub)`: `jev smoke`, `jev ledger-summary`)
- `tests/inference/mock_jev.py` (shared MockTransport factory)
- `tests/inference/test_keys.py`, `test_questions.py`, `test_client.py`, `test_ledger.py`, `test_budget.py`, `test_cache.py`, `test_runner.py`

---

### Task 3.1: Key loading

- [ ] **Step 1: Test**

```python
# tests/inference/test_keys.py
import pytest

from atlas.inference import keys

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def test_env_var_wins_and_keychain_is_not_called(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    assert keys.get_api_key() == CANARY


def test_missing_key_error_does_not_leak(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(keys, "_keychain", lambda: None)
    with pytest.raises(keys.MissingKey) as exc:
        keys.get_api_key()
    assert "Keychain" in str(exc.value)


def test_base_url_default_and_override(monkeypatch):
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    assert keys.base_url() == "https://api.typesafe.ai"
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:9")
    assert keys.base_url() == "http://127.0.0.1:9"
```

- [ ] **Step 2: Fail. Step 3: Implement**

```python
# src/atlas/inference/keys.py
"""API key and endpoint. Order: TYPESAFE_API_KEY env var, then macOS Keychain
(service typesafe-jev-api-key, account jev-opportunity-atlas). The key is returned to
the caller only; it is never logged or stored."""

import os
import subprocess

SERVICE, ACCOUNT = "typesafe-jev-api-key", "jev-opportunity-atlas"


class MissingKey(RuntimeError):
    pass


def _keychain() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def get_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY") or _keychain()
    if not key:
        raise MissingKey(f"No Jev key: set TYPESAFE_API_KEY or add Keychain item {SERVICE}/{ACCOUNT}")
    return key


def base_url() -> str:
    return os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
```

- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 3.2: Question sets and state building

- [ ] **Step 1: Test**

```python
# tests/inference/test_questions.py
import json

from atlas.inference.questions import build_state, canonical_json, load_question_set, questions_for


def test_load_and_version_label():
    qs = load_question_set("screen", 0)
    assert qs.label == "screen@0" and "firsthand_problem" in qs.questions


def test_sentence_marker_expands_per_comment():
    qs = load_question_set("deep", 0)
    q = questions_for(qs, sentences=["A.", "B.", "C."])
    assert q["support_sentence"]["criteria"] == {"s0": None, "s1": None, "s2": None}
    assert qs.questions["support_sentence"]["criteria"] == "SENTENCE_IDS"  # original untouched


def test_state_truncates_parent_and_labels_sentences():
    st = build_state(comment="C", parent="p" * 2000, story_title="T", thread_type="ask_hn",
                     sentences=["One.", "Two."], fields=["comment", "parent", "story_title", "thread_type", "sentences"])
    assert len(st["parent"]) == 1500 and st["sentences"] == {"s0": "One.", "s1": "Two."}


def test_state_includes_only_requested_fields():
    st = build_state(comment="C", parent=None, story_title="T", thread_type="story",
                     sentences=["x"], fields=["comment", "story_title"])
    assert st == {"comment": "C", "story_title": "T"}


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == canonical_json({"a": [2, {"c": 2, "d": 1}], "b": 1})
    assert json.loads(canonical_json({"x": "é"})) == {"x": "é"}
```

- [ ] **Step 2: Fail. Step 3: Implement** `QuestionSet(name, version, label, state_fields, questions)` frozen dataclass; `load_question_set(name, version)` reads `paths.CONFIGS / "questions" / f"{name}.v{version}.json"`; `questions_for(qs, sentences)` returns a deep copy with any `"criteria": "SENTENCE_IDS"` replaced by `{f"s{i}": None ...}` (cap 255); `build_state(...)` builds the dict with `parent` truncated to 1,500 characters (empty string when None) and `sentences` as `{"s0": ...}`; `canonical_json(obj)` is `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 3.3: Mock Jev and the client with observable retries

- [ ] **Step 1: Shared mock**

```python
# tests/inference/mock_jev.py
"""Deterministic fake of POST /v1/systemone. `script` is a list of outcomes consumed
per request: "ok", "429", "529", "500", "422", "timeout", "null_usage", "bad_json"."""

import json

import httpx


def answer_for(q: dict) -> dict:
    if q["type"] == "noul":
        return {"type": "noul", "noul": 0.8}
    if q["type"] == "choice":
        opts = list(q["criteria"])
        return {"type": "choice", "choice": opts[0], "confidence": 0.9,
                "probabilities": {o: (1.0 if i == 0 else 0.0) for i, o in enumerate(opts)}}
    n = len(q["criteria"])
    return {"type": "score", "score": 1.0, "confidence": 0.8,
            "legend": {str(i): str(c) for i, c in enumerate(q["criteria"])},
            "probabilities": {str(i): (1.0 if i == 1 else 0.0) for i in range(n)}}


def make_transport(script: list[str], seen: list | None = None) -> httpx.MockTransport:
    queue = list(script)
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        if seen is not None:
            seen.append(request)
        outcome = queue.pop(0) if queue else "ok"
        rid = {"x-typesafe-request-id": f"req_{counter['n']:04d}"}
        if outcome == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if outcome in ("429", "529", "500"):
            return httpx.Response(int(outcome), headers={**rid, "retry-after": "0"}, json={"error": outcome})
        if outcome == "422":
            return httpx.Response(422, headers=rid, json={"error": "bad request"})
        if outcome == "bad_json":
            return httpx.Response(200, headers=rid, content=b"{not json")
        body = json.loads(request.content)
        usage = None if outcome == "null_usage" else {"input_tokens": 300, "output_tokens": 20}
        return httpx.Response(200, headers=rid, json={
            "model": "jev-1.13.0",
            "answers": {k: answer_for(q) for k, q in body["questions"].items()},
            "usage": usage,
        })

    return httpx.MockTransport(handler)
```

- [ ] **Step 2: Test**

```python
# tests/inference/test_client.py
import asyncio

import httpx
import pytest

from atlas.inference.client import JevClient, RetryPolicy
from tests.inference.mock_jev import make_transport

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64
Q = {"q": {"type": "noul", "instructions": "Is `comment` a problem?"}}


def run(script, **kw):
    seen = []
    client = JevClient(api_key=CANARY, base="http://mock", transport=make_transport(script, seen),
                       policy=RetryPolicy(max_attempts=4, backoff_initial=0, backoff_max=0), **kw)
    result = asyncio.run(client.evaluate({"comment": "x"}, Q, model="jev-1.13.0"))
    return result, seen


def test_success_records_one_attempt_with_request_id_and_usage():
    res, seen = run(["ok"])
    assert res.ok and len(res.attempts) == 1
    a = res.attempts[0]
    assert (a.http_status, a.request_id, a.input_tokens, a.model_returned) == (200, "req_0001", 300, "jev-1.13.0")
    assert seen[0].headers["authorization"] == f"Bearer {CANARY}"


def test_retries_are_visible_as_separate_attempts():
    res, _ = run(["429", "529", "ok"])
    assert res.ok and [a.http_status for a in res.attempts] == [429, 529, 200]
    assert [a.error_type for a in res.attempts] == ["rate_limited", "overloaded", None]


def test_timeout_is_an_unknown_charge_not_free():
    res, _ = run(["timeout", "ok"])
    assert res.attempts[0].error_type == "timeout" and res.attempts[0].charge_known is False
    assert res.attempts[1].charge_known is True


def test_null_usage_marks_charge_unknown_but_keeps_answers():
    res, _ = run(["null_usage"])
    assert res.ok and res.attempts[0].input_tokens is None and res.attempts[0].charge_known is False


def test_non_retryable_422_stops():
    res, _ = run(["422"])
    assert not res.ok and len(res.attempts) == 1
    assert res.attempts[0].error_type == "invalid_request" and res.attempts[0].charge_known is True


def test_bad_json_is_validation_failure():
    res, _ = run(["bad_json", "bad_json", "bad_json", "bad_json"])
    assert not res.ok and all(a.validation == "invalid_json" for a in res.attempts)


def test_key_never_in_reprs_or_errors():
    res, _ = run(["500", "500", "500", "500"])
    blob = repr(res) + "".join(repr(a) for a in res.attempts)
    assert CANARY not in blob and not res.ok
```

- [ ] **Step 3: Fail. Step 4: Implement** `client.py`:
  - `RetryPolicy(max_attempts=4, backoff_initial=1.0, backoff_max=16.0, retry_statuses={408, 429, 500, 502, 503, 504, 529}, timeout_s=30.0)`.
  - `Attempt` dataclass: `attempt`, `started_at`, `ended_at` (UTC ISO), `request_ms`, `backoff_ms`, `http_status`, `request_id`, `error_type` (`None | "rate_limited" | "overloaded" | "server_error" | "timeout" | "connection" | "invalid_request" | "auth" | "invalid_json" | "schema"`), `validation` (`"ok" | "invalid_json" | "schema" | "not_attempted"`), `input_tokens`, `output_tokens`, `model_returned`, `charge_known` (True only when a 200 response had integer usage; 4xx other than 429 are treated as not charged and `charge_known=True` with zero tokens; timeouts, connection errors after send, 5xx, 529, and null usage are `charge_known=False`).
  - `CallResult`: `ok`, `answers` (dict or None), `attempts` (list), `model_returned`.
  - `JevClient(api_key, base, transport=None, policy=RetryPolicy())`; `async evaluate(state, questions, model) -> CallResult`. Build the body `{"state", "model", "questions"}`, post with header `Authorization: Bearer <key>`, read `x-typesafe-request-id`, parse and validate (every question id present in `answers` with a matching `type`). Honor `retry-after` seconds when present, else exponential backoff capped at `backoff_max`. Store the key in a private attribute excluded from `__repr__` (`field(repr=False)` or a custom `__repr__`).
- [ ] **Step 5: Pass. Commit and push.**

### Task 3.4: Ledger

- [ ] **Step 1: Test**

```python
# tests/inference/test_ledger.py
import json

from atlas import contracts as c
from atlas.inference.ledger import Ledger, summarize


def row(**over):
    base = {k: None for k in c.LEDGER_FIELDS}
    base.update(run_id="r1", logical_call_id="L1", attempt=1, cost_class="calculated",
                cost_usd=0.0000126, input_tokens=300, output_tokens=20, cache="miss")
    base.update(over)
    return base


def test_rows_have_exact_fields_in_order(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(row())
    line = (tmp_path / "ledger.jsonl").read_text().splitlines()[0]
    assert list(json.loads(line)) == list(c.LEDGER_FIELDS)


def test_unknown_field_is_rejected(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    try:
        led.append({**row(), "authorization": "x"})
    except KeyError:
        return
    raise AssertionError("extra field accepted")


def test_summary_separates_cost_classes(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(row())
    led.append(row(logical_call_id="L2", attempt=1, cost_class="unknown", cost_usd=None, input_tokens=None))
    led.append(row(logical_call_id="L2", attempt=2))
    led.append(row(logical_call_id="L3", cost_class="replay", cost_usd=0.0, cache="hit"))
    s = summarize(tmp_path / "ledger.jsonl")
    assert s["attempts"] == 4 and s["logical_calls"] == 3
    assert s["calculated_usd"] == 2 * 0.0000126 and s["unknown_attempts"] == 1
    assert s["replays"] == 1 and s["retried_calls"] == 1
```

- [ ] **Step 2: Fail. Step 3: Implement** `Ledger(path)` with `append(row: dict)` that raises `KeyError` on any key outside `LEDGER_FIELDS`, fills missing keys with `None`, writes one JSON line in `LEDGER_FIELDS` order, flushes, and `os.fsync`s every 50 rows and on `close()`. `summarize(path) -> dict` with `attempts`, `logical_calls`, `retried_calls`, `calculated_usd`, `unknown_attempts`, `replays`, `input_tokens`, `p50_request_ms`, `p95_request_ms` (numpy percentile over non-replay attempts with a status), `by_status`.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 3.5: Budget guard

- [ ] **Step 1: Test**

```python
# tests/inference/test_budget.py
import asyncio

import pytest

from atlas.inference.budget import BudgetExceeded, BudgetGuard


def test_reserve_settle_and_stop():
    g = BudgetGuard(cap_usd=0.001, usd_per_input_token=0.042e-6, worst_case_tokens_unknown=8000)
    r = asyncio.run(g.reserve(est_tokens=10_000))           # 0.00042
    asyncio.run(g.settle(r, actual_tokens=9_000, known=True))
    assert g.spent_usd == pytest.approx(9_000 * 0.042e-6) and g.reserved_usd == 0
    with pytest.raises(BudgetExceeded):
        asyncio.run(g.reserve(est_tokens=20_000))           # would pass the cap


def test_unknown_charges_count_at_worst_case():
    g = BudgetGuard(cap_usd=1.0, usd_per_input_token=0.042e-6, worst_case_tokens_unknown=8000)
    r = asyncio.run(g.reserve(est_tokens=500))
    asyncio.run(g.settle(r, actual_tokens=None, known=False))
    assert g.unknown_attempts == 1 and g.committed_usd == pytest.approx(8000 * 0.042e-6)


def test_resume_from_ledger_summary():
    g = BudgetGuard.from_summary({"calculated_usd": 0.5, "unknown_attempts": 2}, cap_usd=1.0,
                                 usd_per_input_token=0.042e-6, worst_case_tokens_unknown=8000)
    assert g.committed_usd == pytest.approx(0.5 + 2 * 8000 * 0.042e-6)
```

- [ ] **Step 2: Fail. Step 3: Implement** `BudgetGuard` with an `asyncio.Lock`: `committed_usd = spent_usd + unknown_attempts * worst_case_cost + reserved_usd`. `reserve(est_tokens)` raises `BudgetExceeded` if `committed + est_cost > cap`, else records a reservation and returns a handle. `settle(handle, actual_tokens, known)` releases the reservation and adds actual cost (known) or increments `unknown_attempts` (unknown). `from_summary(...)` rebuilds state from `ledger.summarize` output at restart.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 3.6: Cache

- [ ] **Step 1: Test**

```python
# tests/inference/test_cache.py
from atlas.inference.cache import ResponseCache, cache_key


def test_key_depends_on_every_input():
    base = dict(state={"comment": "x"}, questions={"q": {"type": "noul", "instructions": "?"}},
                question_set="screen@0", model="jev-1.13.0")
    k = cache_key(**base)
    assert k == cache_key(**base)
    for field, value in [("state", {"comment": "y"}), ("question_set", "screen@1"), ("model", "jev-1.14.0")]:
        assert cache_key(**{**base, field: value}) != k


def test_put_get_keeps_original_provenance(tmp_path):
    c = ResponseCache(tmp_path / "jev.sqlite")
    c.put("k1", {"answers": {"q": {"type": "noul", "noul": 0.5}}}, run_id="r1", logical_call_id="L9",
          request_id="req_1", input_tokens=300)
    hit = c.get("k1")
    assert hit["response"]["answers"]["q"]["noul"] == 0.5
    assert (hit["run_id"], hit["logical_call_id"], hit["request_id"], hit["input_tokens"]) == ("r1", "L9", "req_1", 300)
    assert c.get("missing") is None
```

- [ ] **Step 2: Fail. Step 3: Implement** `cache_key(state, questions, question_set, model)` as SHA-256 of `canonical_json({"state":..., "questions":..., "question_set":..., "model":...})`. `ResponseCache(path)` over sqlite3 with table `cache(key TEXT PRIMARY KEY, response TEXT, run_id TEXT, logical_call_id TEXT, request_id TEXT, input_tokens INTEGER, created_at TEXT)`, WAL mode, `put` uses `INSERT OR IGNORE` (first answer wins, never overwritten).
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 3.7: Batch runner with resume

- [ ] **Step 1: Test**

```python
# tests/inference/test_runner.py
import asyncio

import pyarrow.parquet as pq

from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient, RetryPolicy
from atlas.inference.questions import load_question_set
from atlas.inference.runner import RunContext, run_batch
from tests.inference.mock_jev import make_transport

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def items(n):
    return [{"comment_id": i, "comment": f"text {i}", "parent": "", "story_title": "T",
             "thread_type": "story", "sentences": [f"text {i}"]} for i in range(n)]


def ctx(tmp_path, script, cap=1.0):
    client = JevClient(api_key=CANARY, base="http://mock", transport=make_transport(script),
                       policy=RetryPolicy(backoff_initial=0, backoff_max=0))
    guard = BudgetGuard(cap_usd=cap, usd_per_input_token=0.042e-6, worst_case_tokens_unknown=8000)
    return RunContext(run_id="r1", run_dir=tmp_path / "r1", client=client, guard=guard,
                      model="jev-1.13.0", price_version="typesafe-2026-09-28",
                      cache_path=tmp_path / "cache.sqlite", concurrency=4)


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
```

- [ ] **Step 2: Fail. Step 3: Implement** `runner.py`:
  - `RunContext` dataclass (fields above, mutable).
  - `async run_batch(ctx, items, qs) -> dict`. For each item: build state with `build_state(..., fields=qs.state_fields)` and questions with `questions_for`; compute `cache_key`; skip if `ctx.run_dir / "done.jsonl"` already lists the comment for this question set; on cache hit, write answers with `cache_hit=True` and a ledger row `cost_class="replay"`, `cache="hit"`; else estimate tokens as `ceil(len(canonical_json(body).encode()) / 3.2)`, reserve, call, settle, write one ledger row per attempt (`cost_usd = input_tokens * price` when known, `cost_class="calculated"`; else `None` and `"unknown"`), put successful responses in the cache, write answer rows (contract `ANSWERS`) to `run_dir/answers/part-<n>.parquet` in batches of 500 items, and append the comment ID to `done.jsonl`. On `BudgetExceeded`, stop dispatching, drain in-flight tasks, flush, and return `stopped="budget"`.
  - Concurrency with an `asyncio.Semaphore(ctx.concurrency)`; `queue_ms` in the ledger is the time between task creation and semaphore acquisition.
  - Return `{"completed", "failed", "skipped_completed", "cache_hits", "new_requests", "stopped", "wall_s"}`.
  - Write `run_dir/run_manifest.json` at start if absent: run_id, model, question set label and file SHA-256, price version, cap, git commit, started_at. Never overwrite an existing manifest; if its question set or model differ, raise.
- [ ] **Step 4: Pass. Split the runner into `runner.py` and `runner_io.py` if it passes 350 lines. Step 5: Commit and push.**

### Task 3.8: CLI

- [ ] **Step 1:** `inference/cli.py` with `register(sub)`:
  - `jev smoke --budget smoke`: one call on a fixed synthetic comment through the full runner into `runs/smoke-<utc timestamp>/`, prints the ledger summary. Requires the `smoke` cap from `configs/budgets.toml`.
  - `jev ledger-summary --run <run_id>`: prints `summarize` as JSON.
- [ ] **Step 2:** Test `ledger-summary` on a ledger written in `tmp_path`.
- [ ] **Step 3: Commit, push, ruff, pytest, open the PR, print PR URL and pytest line.**

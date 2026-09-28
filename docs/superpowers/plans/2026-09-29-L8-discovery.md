# L8: Discovery-lane search (Algolia) for the one-finding spike

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l8-discovery

**Goal:** Given a candidate problem statement and search queries, pull matching HN comments from HN Search (Algolia) inside the frozen window, log every request, and match hits back to snapshot comment IDs, so the spike can ask Jev one problem-statement question per comment. Results are discovery-lane only and never used for prevalence.

**Architecture:** An async httpx client over `https://hn.algolia.com/api/v1/search` with `tags=comment` and `numericFilters=created_at_i>=START,created_at_i<END`. Algolia caps results at 1,000 per query, so each query is split into time slices that each return fewer than 1,000 hits (halve a slice until it fits). Every request is logged. Hits are matched to `comments.parquet` by ID; hits outside the snapshot are listed as `outside_frame`, never added to it.

**Tech Stack:** Python 3.11, httpx (MockTransport in tests), pyarrow, duckdb.

Read first: `AGENTS.md`, `src/atlas/contracts.py`, spec sections 3 and 4.

**Files you own:**
- `src/atlas/discovery/__init__.py`, `src/atlas/discovery/algolia.py`, `src/atlas/discovery/match.py`, `src/atlas/discovery/cli.py` (`register(sub)`: `discover search`)
- `tests/discovery/__init__.py` (exists from Wave 0), `tests/discovery/test_algolia.py`, `tests/discovery/test_match.py`

### Task 8.1: Sliced search with request log

- [ ] **Step 1: Test**

```python
# tests/discovery/test_algolia.py
import asyncio
import re

import httpx

from atlas.discovery.algolia import search_all


def make_transport(total_by_slice):
    calls = []

    def handler(request):
        params = dict(request.url.params)
        m = re.fullmatch(r"created_at_i>=(\d+),created_at_i<(\d+)", params["numericFilters"])
        lo, hi = int(m.group(1)), int(m.group(2))
        n = sum(1 for t in total_by_slice if lo <= t < hi)
        hits = [{"objectID": str(t), "created_at_i": t} for t in total_by_slice if lo <= t < hi][:1000]
        calls.append((lo, hi))
        return httpx.Response(200, json={"nbHits": n, "hits": hits, "nbPages": 1})

    return httpx.MockTransport(handler), calls


def test_slices_until_each_query_fits():
    times = list(range(0, 3000))  # 3000 hits over [0, 3000)
    transport, calls = make_transport(times)
    out = asyncio.run(search_all("stripe payouts", 0, 3000, transport=transport))
    assert sorted(int(h["objectID"]) for h in out["hits"]) == times
    assert all(r["n_hits"] < 1000 for r in out["requests"] if r["used"])
    assert {"query", "lo", "hi", "status", "n_hits", "retrieved_at", "sha256"} <= set(out["requests"][0])
```

The client must send `numericFilters` exactly as `created_at_i>=LO,created_at_i<HI`.

- [ ] **Step 2: Fail. Step 3: Implement** `search_all(query, lo, hi, transport=None, per_page=1000, pause_s=0.2) -> dict`: request `[lo, hi)`; if `nbHits >= 1000`, split in half and recurse; else fetch the page(s). Log every request (query, lo, hi, status, n_hits, retrieved_at, SHA-256 of body, used flag). Respect 429 with backoff. Stay under 1 request per 0.2 s.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 8.2: Match to the snapshot

- [ ] **Step 1: Test** (`test_match.py`): given hit IDs `[1, 2, 99]` and a snapshot `comments.parquet` with eligible IDs `{1, 2}`, `match_hits` returns `{"in_frame": [1, 2], "outside_frame": [99], "ineligible": []}`.
- [ ] **Step 2: Fail. Step 3: Implement** `match_hits(hit_ids, snapshot_dir) -> dict` with DuckDB.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 8.3: CLI

- [ ] `discover search --name <candidate_slug> --query "<text>" [--query ...] --snapshot <id>`: runs every query over the frozen window, writes `data/discovery/<slug>/hits.parquet` (IDs, query, lane="discovery"), `requests.jsonl`, and `manifest.json` (queries, reason field from `--reason`, window, counts, snapshot ID). Never writes HN text outside `data/`.
- [ ] Commit, push, ruff, pytest, open the PR, print PR URL and pytest line.

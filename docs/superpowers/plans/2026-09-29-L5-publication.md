# L5: Allowlisted export, release bundles, rehydrate, restore, claims check

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l5-publication

**Goal:** Produce public release bundles that contain only allowlisted, scanned, text-free artifacts; let anyone restore and verify them; rebuild HN text from the official API; and recompute every X claim from saved answers.

**Architecture:** An export step copies allowlisted files into `exports/<release>/`, strips forbidden columns, splits large files into chunks under 1.9 GiB, writes `SHA256SUMS` and `release_manifest.json`, and runs the secret scanner over every staged file. Restore downloads assets with `gh release download`, verifies hashes and schema versions, and reassembles chunks. Rehydrate fetches comment text by ID and compares hashes. Claims are YAML entries with a DuckDB SQL query each.

**Tech Stack:** Python 3.11, pyarrow, duckdb, pyyaml, httpx, gh CLI.

Read first: `AGENTS.md`, `src/atlas/contracts.py`, `src/atlas/publication/secret_scan.py`, spec sections 9 and 11.

**Files you own:**
- `src/atlas/publication/allowlist.py`
- `src/atlas/publication/export.py`
- `src/atlas/publication/restore.py`
- `src/atlas/publication/rehydrate.py`
- `src/atlas/publication/claims.py`
- `src/atlas/publication/cli.py` (`register(sub)`: `publish stage`, `publish check`, `restore`, `rehydrate`, `claims check`)
- `claims/claims.yaml` (empty list with a commented example)
- `tests/publication/__init__.py`, `test_export.py`, `test_restore.py`, `test_rehydrate.py`, `test_claims.py`

Add dependency: `uv add pyyaml`.

---

### Task 5.1: Allowlist and column stripping

- [ ] **Step 1: Test**

```python
# tests/publication/test_export.py
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.publication.export import ExportError, stage_release

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def make_workspace(tmp_path):
    snap = tmp_path / "data" / "snapshots" / "s1"
    snap.mkdir(parents=True)
    pq.write_table(pa.table({"id": [1, 2], "text_norm": ["a", "b"], "author": ["u1", "u2"],
                             "text_html": ["a", "b"], "text_sha256": ["h1", "h2"], "eligible": [True, False]}),
                   snap / "comments.parquet")
    (snap / "manifest.json").write_text(json.dumps({"schema_version": 1, "snapshot_id": "s1"}))
    run = tmp_path / "runs" / "r1"
    (run / "answers").mkdir(parents=True)
    pq.write_table(pa.table({"comment_id": [1], "question_id": ["q"], "noul": [0.5]}), run / "answers" / "part-0.parquet")
    (run / "ledger.jsonl").write_text('{"run_id": "r1", "cost_usd": 0.1}\n')
    (run / "debug.log").write_text("anything")
    return tmp_path


def test_stage_strips_text_and_authors_and_skips_unlisted(tmp_path):
    ws = make_workspace(tmp_path)
    out = stage_release(ws, release="v0-test", snapshot_id="s1", run_ids=["r1"])
    comments = pq.read_table(out / "snapshot" / "comments_public.parquet")
    assert set(comments.column_names) == {"id", "text_sha256", "eligible"}
    assert (out / "runs" / "r1" / "ledger.jsonl").exists()
    assert not (out / "runs" / "r1" / "debug.log").exists()
    sums = (out / "SHA256SUMS").read_text()
    assert "runs/r1/ledger.jsonl" in sums
    manifest = json.loads((out / "release_manifest.json").read_text())
    assert manifest["release"] == "v0-test" and manifest["contains_hn_text"] is False


def test_secret_in_any_staged_file_blocks(tmp_path):
    ws = make_workspace(tmp_path)
    (ws / "runs" / "r1" / "ledger.jsonl").write_text(json.dumps({"note": CANARY}) + "\n")
    with pytest.raises(ExportError) as exc:
        stage_release(ws, release="v0-test", snapshot_id="s1", run_ids=["r1"])
    assert "typesafe-api-key" in str(exc.value) and CANARY not in str(exc.value)
```

- [ ] **Step 2: Fail. Step 3: Implement**
  - `allowlist.py`: `SNAPSHOT_FILES = {"comments.parquet": ("id", "time", "month", "story_id", "parent_id", "depth", "thread_type", "in_window", "lang", "word_count", "eligible", "exclusion_reason", "text_sha256"), "stories.parquet": ("id", "time", "type", "thread_type", "score", "descendants", "in_window", "url"), "coverage.parquet": None}` where `None` means copy as is; `RUN_FILES = ("ledger.jsonl", "run_manifest.json", "answers/*.parquet", "eval_*.json", "pilot_report.md")`; `EXTRA = ("manifests/**/*.json", "claims/claims.yaml", "taxonomy/**/*.json")`. Story titles and `text_*` columns are excluded on purpose. Columns absent from a source file are skipped, not errors.
  - `export.py`: `stage_release(root, release, snapshot_id, run_ids) -> Path` builds `root/exports/<release>/` fresh (refuse if it exists), writes `<name minus .parquet>_public.parquet` with only allowlisted columns, copies allowlisted run files, scans every staged file with `secret_scan.scan_paths` and raises `ExportError` listing rule and relative path (never the match) on any hit, then writes `SHA256SUMS` (sorted, `sha256  relpath` lines) and `release_manifest.json` (`release`, `snapshot_id`, `run_ids`, `schema_version`, `contains_hn_text: false`, `created_at`, `code_commit`, file count and bytes).
  - `chunk_large_files(dir, limit=1_900_000_000)`: split any file above the limit into `<name>.part000`, `.part001`, … and record them in the manifest under `chunks`.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 5.2: Restore and verify

- [ ] **Step 1: Test**

```python
# tests/publication/test_restore.py
from atlas.publication.export import stage_release
from atlas.publication.restore import verify_release
from tests.publication.test_export import make_workspace


def test_verify_passes_then_detects_tamper(tmp_path):
    ws = make_workspace(tmp_path)
    out = stage_release(ws, release="v0-test", snapshot_id="s1", run_ids=["r1"])
    assert verify_release(out)["ok"] is True
    (out / "runs" / "r1" / "ledger.jsonl").write_text("changed\n")
    report = verify_release(out)
    assert report["ok"] is False and report["bad"] == ["runs/r1/ledger.jsonl"]


def test_chunks_reassemble(tmp_path):
    from atlas.publication.export import chunk_large_files
    from atlas.publication.restore import reassemble
    d = tmp_path / "rel"
    d.mkdir()
    (d / "big.bin").write_bytes(b"x" * 2500)
    chunks = chunk_large_files(d, limit=1000)
    assert len(chunks["big.bin"]) == 3 and not (d / "big.bin").exists()
    reassemble(d, chunks)
    assert (d / "big.bin").read_bytes() == b"x" * 2500
```

- [ ] **Step 2: Fail. Step 3: Implement** `restore.py`: `download(release, repo, dest)` runs `gh release download <release> -R <repo> -D <dest>` then unpacks any `*.tar.zst` bundle; `reassemble(dir, chunks)`; `verify_release(dir) -> {"ok", "bad", "missing", "schema_version"}` checking every `SHA256SUMS` line and that `release_manifest.json` has `schema_version == contracts.SCHEMA_VERSION`. Bundle packing (`pack_release(dir) -> list[Path]`) writes `<release>.tar.zst` (zstandard stream over `tarfile`) and chunks it when larger than the limit.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 5.3: Rehydrate text from the official API

- [ ] **Step 1: Test**

```python
# tests/publication/test_rehydrate.py
import asyncio
import hashlib
import json

import httpx

from atlas.publication.rehydrate import rehydrate


def h(t):
    return hashlib.sha256(t.encode()).hexdigest()


def test_matches_changed_and_missing():
    items = {1: {"id": 1, "text": "Same text"}, 2: {"id": 2, "text": "Edited later"}, 3: None}

    async def handler(request):
        i = int(request.url.path.rsplit("/", 1)[1].split(".")[0])
        return httpx.Response(200, content=json.dumps(items[i]).encode())

    expected = {1: h("Same text"), 2: h("Original"), 3: h("Gone")}
    out = asyncio.run(rehydrate(expected, transport=httpx.MockTransport(handler), concurrency=2,
                                normalize=lambda t: t))
    assert out["texts"][1] == "Same text"
    assert out["status"] == {1: "match", 2: "changed", 3: "missing"}
    assert out["summary"] == {"match": 1, "changed": 1, "missing": 1}
```

- [ ] **Step 2: Fail. Step 3: Implement** `async rehydrate(expected: dict[int, str], transport=None, concurrency=32, api_base="https://hacker-news.firebaseio.com/v0", normalize=None) -> dict`: fetch each ID, normalize the item's `text` with `normalize` (default: a lazy import of `atlas.sources.htmltext.html_to_text`, which lane L1 provides; the test passes an identity function so this lane does not depend on L1), compare SHA-256 of the normalized text, classify `match`, `changed`, or `missing` (null, deleted, or dead). CLI writes texts only to `data/rehydrated/` (gitignored), never to exports.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 5.4: Claims check

- [ ] **Step 1: Test**

```python
# tests/publication/test_claims.py
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.publication.claims import check_claims


def test_claim_matches_and_drift_fails(tmp_path):
    pq.write_table(pa.table({"comment_id": [1, 2, 3, 4], "firsthand": [1, 1, 0, 0]}), tmp_path / "t.parquet")
    claims = [
        {"id": "c1", "text": "Half of screened comments were firsthand.", "value": 0.5, "tolerance": 0.001,
         "sql": "SELECT avg(firsthand) FROM read_parquet('{root}/t.parquet')",
         "run_id": "r1", "lane": "breadth", "denominator": "screened comments"},
        {"id": "c2", "text": "Stale number.", "value": 0.9, "tolerance": 0.001,
         "sql": "SELECT avg(firsthand) FROM read_parquet('{root}/t.parquet')",
         "run_id": "r1", "lane": "breadth", "denominator": "screened comments"},
    ]
    report = check_claims(claims, root=tmp_path)
    assert report["c1"]["ok"] is True and report["c2"]["ok"] is False
    assert report["c2"]["actual"] == 0.5


def test_required_fields_enforced(tmp_path):
    report = check_claims([{"id": "c3", "text": "x", "value": 1, "sql": "SELECT 1"}], root=tmp_path)
    assert report["c3"]["ok"] is False and "missing" in report["c3"]["error"]
```

- [ ] **Step 2: Fail. Step 3: Implement** `check_claims(claims, root) -> dict`: required fields `id, text, value, tolerance, sql, run_id, lane, denominator`; `lane` must be `breadth` or `discovery`; run the SQL with DuckDB after formatting `{root}`; the result must be a single scalar; `ok` when `abs(actual - value) <= tolerance`. `load_claims(path)` reads `claims/claims.yaml`.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 5.5: CLI

- [ ] **Step 1:** `publication/cli.py` with `register(sub)`:
  - `publish stage --release <tag> --snapshot <id> --run <id> [--run <id> ...]`
  - `publish check --release <tag>`: verify plus a second full secret scan; also runs `gitleaks dir exports/<tag>` when gitleaks is installed.
  - `restore --release <tag> [--repo hanselhansel/jev-opportunity-atlas] [--dest DIR]`: download, reassemble, verify.
  - `rehydrate --release-dir DIR [--limit N]`
  - `claims check [--file claims/claims.yaml]`: exits 1 on any failure.
  - Uploading assets stays a manual, reviewed step in plan 2 (`gh release create`), so this lane never publishes anything.
- [ ] **Step 2:** Test `claims check` exit codes on a temp YAML file.
- [ ] **Step 3: Commit, push, ruff, pytest, open the PR, print PR URL and pytest line.**

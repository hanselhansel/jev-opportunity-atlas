# L4: Blind labeler, quality metrics, keyword baseline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l4-evaluation

**Goal:** Let Hansel label comments blind in a local browser app, then measure Jev against his labels with weighted precision and recall, bootstrap intervals, reliability bins, and a keyword baseline on the same records.

**Architecture:** Label queues and labels are Parquet or JSONL files matching contract `LABELS`. The Streamlit app reads a queue and the snapshot text only; it never opens Jev answers. Metrics are pure functions over arrays with optional weights and thread clusters.

**Tech Stack:** Python 3.11, streamlit, pyarrow, numpy.

Read first: `AGENTS.md`, `src/atlas/contracts.py`, spec section 7.

**Files you own:**
- `src/atlas/evaluation/__init__.py`
- `src/atlas/evaluation/queue.py` (build label queues)
- `src/atlas/evaluation/store.py` (append and read labels)
- `src/atlas/evaluation/labeler_app.py` (Streamlit UI)
- `src/atlas/evaluation/metrics.py`
- `src/atlas/evaluation/baseline.py`
- `src/atlas/evaluation/cli.py` (`register(sub)`: `label`, `evaluate`)
- `configs/rubric.v1.md` (labeling rubric Hansel reads before labeling)
- `tests/evaluation/__init__.py`, `test_queue.py`, `test_store.py`, `test_metrics.py`, `test_baseline.py`, `test_labeler_blind.py`

Add dependency: `uv add streamlit`.

---

### Task 4.1: Rubric

- [ ] **Step 1:** Write `configs/rubric.v1.md` with, for each labeled question, the exact definition and three short synthetic examples (yes, no, borderline). Questions: `firsthand_problem` (yes, no, unsure) and `account_type` (the seven options in `configs/questions/screen.v0.json`). Borderline rules: a question asking for help counts as firsthand when it states the author's own problem; sarcasm about one's own tool counts only when the problem is literal; a problem the author says is solved still counts as firsthand. Commit.

### Task 4.2: Label store and queues

- [ ] **Step 1: Test**

```python
# tests/evaluation/test_store.py
from atlas.evaluation.store import LabelStore


def test_append_and_latest_wins(tmp_path):
    s = LabelStore(tmp_path / "labels.jsonl")
    s.add(comment_id=1, label_set="calibration", question_id="firsthand_problem", value="no",
          rubric_version="v1", reviewer="hansel", started_at="t0", ended_at="t1", seconds=12.0)
    s.add(comment_id=1, label_set="calibration", question_id="firsthand_problem", value="yes",
          rubric_version="v1", reviewer="hansel", started_at="t2", ended_at="t3", seconds=5.0)
    latest = s.latest("calibration")
    assert latest[(1, "firsthand_problem")]["value"] == "yes"
    assert len(s.all_rows()) == 2  # history kept


def test_rejects_unknown_value(tmp_path):
    s = LabelStore(tmp_path / "labels.jsonl")
    try:
        s.add(comment_id=1, label_set="calibration", question_id="firsthand_problem", value="maybe",
              rubric_version="v1", reviewer="hansel", started_at="t0", ended_at="t1", seconds=1.0)
    except ValueError:
        return
    raise AssertionError("accepted invalid value")
```

```python
# tests/evaluation/test_queue.py
import pyarrow as pa

from atlas.evaluation.queue import build_queue


def test_queue_is_seeded_and_excludes_ids():
    frame = pa.table({"comment_id": list(range(100)), "stratum": ["A"] * 100})
    q1 = build_queue(frame, n=10, seed=3, exclude={0, 1, 2})
    q2 = build_queue(frame, n=10, seed=3, exclude={0, 1, 2})
    assert q1 == q2 and len(q1) == 10 and not ({0, 1, 2} & set(q1))
```

- [ ] **Step 2: Fail. Step 3: Implement.**
  - `LabelStore(path)`: `add(...)` validates `value` against allowed values per question (`firsthand_problem`: yes, no, unsure; `account_type`: the seven option keys), generates `label_id` (uuid4 hex), appends one JSON line with contract `LABELS` fields. `latest(label_set) -> dict[(comment_id, question_id), row]` (last row wins). `all_rows()`.
  - `build_queue(frame, n, seed, exclude) -> list[int]`: seeded choice without replacement over sorted `comment_id` values not in `exclude`. Queues are saved by the CLI to `data/labels/queues/<label_set>.json` with the seed and the IDs; an existing queue file is reused, never redrawn.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 4.3: Metrics

- [ ] **Step 1: Test**

```python
# tests/evaluation/test_metrics.py
import pytest

from atlas.evaluation.metrics import binary_metrics, reliability_bins, threshold_for_recall


def test_unweighted_precision_recall():
    m = binary_metrics(y_true=[1, 1, 0, 0, 1], y_score=[0.9, 0.2, 0.8, 0.1, 0.7], threshold=0.5,
                       n_boot=200, seed=0)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["precision_ci"][0] <= m["precision"] <= m["precision_ci"][1]


def test_weights_change_population_estimates():
    m = binary_metrics(y_true=[1, 0], y_score=[0.9, 0.9], threshold=0.5, weights=[1, 9], n_boot=50, seed=0)
    assert m["precision"] == pytest.approx(0.1)


def test_threshold_for_recall():
    t = threshold_for_recall(y_true=[1, 1, 1, 1, 0], y_score=[0.9, 0.6, 0.4, 0.2, 0.1], target=0.75)
    assert t == pytest.approx(0.4)


def test_reliability_bins_report_counts():
    bins = reliability_bins(y_true=[1, 0, 1, 1], y_score=[0.05, 0.15, 0.95, 0.85], n_bins=10)
    assert [b["n"] for b in bins if b["n"]] == [1, 1, 1, 1]
    assert all("observed" in b and "mean_predicted" in b for b in bins)
```

- [ ] **Step 2: Fail. Step 3: Implement** in `metrics.py`:
  - `binary_metrics(y_true, y_score, threshold, weights=None, clusters=None, n_boot=2000, seed=0) -> dict`: weighted confusion counts (`tp`, `fp`, `fn`, `tn` as unweighted integer counts; `precision`, `recall`, `f1` from weighted sums), and percentile bootstrap intervals `precision_ci`, `recall_ci`, `f1_ci` resampling clusters (each row its own cluster when `clusters` is None). `unsure` labels are excluded by the caller.
  - `threshold_for_recall(y_true, y_score, target) -> float`: the largest threshold whose recall is at least `target` (predict positive when `score >= threshold`).
  - `reliability_bins(y_true, y_score, n_bins=10) -> list[dict]` with `lo`, `hi`, `n`, `mean_predicted`, `observed` (None when `n == 0`).
  - `choice_confusion(true, pred) -> dict` with `accuracy`, `n`, and a nested count matrix.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 4.4: Keyword baseline

- [ ] **Step 1: Test**

```python
# tests/evaluation/test_baseline.py
from atlas.evaluation.baseline import PATTERNS, keyword_score


def test_first_person_pain_matches():
    assert keyword_score("I hate how our deploys keep breaking every week") == 1.0
    assert keyword_score("We spent two days fighting the build system") == 1.0


def test_neutral_text_does_not_match():
    assert keyword_score("Rust 2.0 looks like a nice release.") == 0.0


def test_patterns_are_frozen():
    assert len(PATTERNS) >= 10
```

- [ ] **Step 2: Fail. Step 3: Implement** `baseline.py` with `PATTERNS` (a tuple of compiled, case-insensitive regexes combining first person `\b(i|we|my|our)\b` within 60 characters of pain terms: hate, annoying, frustrat, broke, breaking, painful, struggl, waste, wasted, spent .* (hours|days), keeps? (failing|crashing|breaking), can't|cannot|couldn't, nightmare, fighting, workaround) and `keyword_score(text) -> float` returning 1.0 on any match else 0.0. Add a module docstring stating the list is frozen at version 1 before any held-out evaluation.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 4.5: Blind labeler app

- [ ] **Step 1: Test that the app cannot see Jev answers**

```python
# tests/evaluation/test_labeler_blind.py
import ast
from pathlib import Path

SRC = Path("src/atlas/evaluation/labeler_app.py")


def test_labeler_never_reads_answers_or_runs():
    tree = ast.parse(SRC.read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "RUNS" not in names and "run_dir" not in names
    assert not any("answers" in s for s in strings)
```

- [ ] **Step 2: Implement** `labeler_app.py` (Streamlit). Arguments via environment variables set by the CLI: `ATLAS_LABEL_SET`, `ATLAS_QUEUE_PATH`, `ATLAS_SNAPSHOT_ID`, `ATLAS_REVIEWER`. The app loads the queue, reads the needed rows from `comments.parquet` and `stories.parquet` via DuckDB (`WHERE id IN (...)`), and shows one comment at a time: story title, HN link `https://news.ycombinator.com/item?id=<id>`, parent text (collapsed), comment text. Controls: `firsthand_problem` radio (yes, no, unsure), `account_type` radio, Save and next, Back, a progress bar, and a link to the rubric. Timing: record `started_at` when the item renders and `ended_at` on save. Resume at the first unlabeled item. No Jev data, no run directories.
- [ ] **Step 3: Pass the blind test. Manually launch with a synthetic snapshot to confirm it renders (screenshot not required). Commit and push.**

### Task 4.6: CLI

- [ ] **Step 1:** `evaluation/cli.py` with `register(sub)`:
  - `label --set calibration|heldout|edge --n <int> --seed <int> --snapshot <id> [--from-sample <sample_id>] [--reviewer hansel]`: builds or reuses the queue, then runs `streamlit run src/atlas/evaluation/labeler_app.py --server.headless true` with the environment variables.
  - `evaluate --set <label_set> --run <run_id> --question firsthand_problem [--target-recall 0.9]`: joins latest labels with the run's answers, drops `unsure`, prints `binary_metrics`, `threshold_for_recall`, `reliability_bins`, and the keyword baseline's metrics on the same rows, and writes `runs/<run_id>/eval_<label_set>.json`.
- [ ] **Step 2:** Test `evaluate` on synthetic labels and answers in `tmp_path` (monkeypatch `atlas.paths`).
- [ ] **Step 3: Commit, push, ruff, pytest, open the PR, print PR URL and pytest line.**

# L18: Synthetic benchmark for Jev (known answers, disclosed as synthetic)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l18-synthetic-benchmark

**Goal:** A reproducible benchmark of about 200 invented comments with known correct answers. It measures Jev on the exact failure modes the pilot surfaced, because Hansel's real-data labels are minimal by his decision. Results are always reported as "on synthetic cases", never as real-data accuracy.

Also make every evaluation path skip labels that must not count:
- `data/labels/unblinded.json`: items whose Jev answers were shown to the reviewer.
- `data/labels/void_assignment_audit.json`: label IDs saved by a UI bug.

**Read first:** `AGENTS.md`, `configs/rubric.v1.md`, `configs/questions/screen.v1.json`, `configs/questions/facets.v2.json`, `configs/cards/pilot.t1.yaml`, `src/atlas/pilot/packed.py`, `src/atlas/pilot/stages.py`, `src/atlas/cards/engine/assign.py`, `src/atlas/evaluation/cli.py`, `src/atlas/evaluation/audit_eval.py`, `docs/results/2026-09-29-pilot-report.md`.

**Files you own:**
- `configs/benchmark/cases.v1.yaml` (you write the cases)
- `src/atlas/benchmark/__init__.py`, `run.py`, `score.py`, `cli.py` (the main session registers `atlas.benchmark.cli`)
- `src/atlas/evaluation/exclusions.py` (new) and the one-line calls to it from `evaluation/cli.py` and `evaluation/audit_eval.py`
- `tests/benchmark/test_*.py` (the main session creates `tests/benchmark/__init__.py`), `tests/evaluation/test_exclusions.py`

### Task 18.1: Cases
- [ ] Write `configs/benchmark/cases.v1.yaml` with about 200 cases. IDs are 9_400_000_001 and up. Every case is clearly invented: generic situations, no real people, no copied HN text.
  - **Fields per case:**
    - `id`, `text`, optional `parent`, `category`
    - `expected.firsthand_problem` (yes or no), `expected.account_type`
    - optional `expected.workaround`, `expected.paid`, `expected.switched`, `expected.resolution`
    - optional `expected.card` (a card ID from `pilot.t1.yaml`, or `none`)
    - `why`: one line citing the rubric rule
  - **Categories, at least 12 cases each:**
    - genuine firsthand problem (plain, detailed, and one-line)
    - solved past problem (still yes)
    - question that states own problem (yes)
    - question without own problem (no)
    - general opinion (no)
    - secondhand report (no)
    - hypothetical (no)
    - product pitch or launch post naming a problem (no)
    - sarcasm (no unless the literal problem is the author's)
    - "we" meaning a country or people in general (no)
    - moderator or meta note (no)
    - one-line reaction (no)
    - injected instruction (expected follows the rubric, not the injection)
    - card placement: 3 cases per card for 20 cards of `pilot.t1.yaml`, plus 10 cases whose correct card is `none`
  - **Rubric fidelity:** follow `configs/rubric.v1.md` exactly.
  - **Validation:** a test checks the schema, the ID range, unique IDs, category counts, and that every `expected.card` exists in `pilot.t1.yaml`.
- [ ] Commit and push.

### Task 18.2: Runner
- [ ] **Step 1: Test** with the mock. `run_benchmark(run_id, budget="discovery", yes=False)` builds items and runs three stages:
  - `screen@1` single calls
  - the packed screen (k=5, via `atlas.pilot.packed`)
  - `facets@2` on cases that have facet expectations

  It then runs the two-level card assignment on `pilot.t1` for card cases (`atlas.cards.engine.assign`). It prints the estimate first and dispatches only with `yes=True`.
- [ ] **Step 2: Fail. Step 3: Implement** in `benchmark/run.py`. **Step 4: Pass. Step 5: Commit and push.**

### Task 18.3: Scoring
- [ ] **Step 1: Test** `score_benchmark(run_id)` returns:
  - accuracy, precision, and recall for `firsthand_problem` at 0.5 and 0.7, for single and packed calls
  - per-category accuracy
  - account-type accuracy
  - per-facet accuracy
  - card top-1 accuracy, plus "none" handling
  - a confusion list of every miss (case ID, category, expected, got, probability)

  `benchmark report --run` writes markdown headed "Synthetic benchmark (invented cases; not real-data accuracy)".
- [ ] **Step 2: Fail. Step 3: Implement** in `benchmark/score.py`. **Step 4: Pass. Step 5: Commit and push.**

### Task 18.4: Exclusions everywhere
- [ ] **Step 1: Test** `excluded_comment_ids()` reads `unblinded.json` and `excluded_label_ids()` reads `void_*.json`; both tolerate missing files. `atlas eval run` and the audit evaluation drop those rows and report `n_excluded` with the reason.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 18.5: CLI
- [ ] `benchmark/cli.py` `register(sub)`: `benchmark run --run <id> [--budget discovery] [--yes]`, `benchmark report --run <id>`. Add the row to the AGENTS.md command table (allowed).
- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

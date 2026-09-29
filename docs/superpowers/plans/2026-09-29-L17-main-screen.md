# L17: Main packed screen at scale (760k comments, $8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l17-main-screen

**Goal:** Screen about 760,000 sampled comments for firsthand problems with Jev at 5 comments per call. The run must:
- stay under TypeSafe's documented 1,200 requests per minute;
- resume without repeating or missing work;
- never hold all items in memory;
- produce a clean per-comment table for the next steps.

The main session runs it; this lane builds and tests it with the mock.

**Measured inputs (pilot `pilot-20260929`, see `docs/results/2026-09-29-pilot-report.md`):**
- Packed screen costs about 251 tokens per comment vs 591 single, with 96.8% agreement with single calls.
- Per-stratum firsthand rates `p_h` and single-call tokens `c_h` come from the pilot run.
- Budget `screen` is $8.00 (`configs/budgets.toml`). The account cap is $25.

**Read first:**
- `AGENTS.md`
- `src/atlas/pilot/packed.py`, `stages.py`
- `src/atlas/inference/runner.py`, `budget.py`, `estimate.py`
- `src/atlas/sampling/design_v2.py`, `yield_alloc.py`, `cli.py`
- `src/atlas/sources/items.py`
- `docs/superpowers/specs/2026-09-29-analysis-design.md` section 4

**Files you own:**
- `src/atlas/screen/__init__.py`, `src/atlas/screen/run.py`, `src/atlas/screen/unpack.py`, `src/atlas/screen/cli.py` (new; the main session registers `atlas.screen.cli` in the CLI registry)
- `src/atlas/inference/runner.py`: the rate limiter only (Task 17.1)
- `src/atlas/sampling/cli.py` and `src/atlas/sampling/yield_alloc.py`: the cost scale only (Task 17.2)
- `tests/screen/test_*.py` (create `tests/screen/`; the main session adds its `__init__.py`), `tests/inference/test_rate_limit.py`, `tests/sampling/test_cost_scale.py`

### Task 17.1: Requests-per-minute limiter in the runner
- [ ] **Step 1: Test** `RunContext(rpm=600)` never starts more than 10 requests in any 1-second window, measured with a fake clock injected into a new `atlas.inference.ratelimit.TokenBucket`. Retries count as requests. `rpm=None` keeps today's behavior. All existing inference tests still pass.
- [ ] **Step 2: Fail. Step 3: Implement** `TokenBucket(rate_per_s, burst)` with `async acquire()`. The runner calls it before every network send (inside the existing `before_send` path), not for cache hits. **Step 4: Pass. Step 5: Commit and push.**

### Task 17.2: Allocation at packed cost
- [ ] **Step 1: Test** `sample allocate-v2 ... --cost-scale 0.425` multiplies every `c_h` by the scale before allocating. The same budget then yields about 2.35 times as many comments. The manifest records `cost_scale` and its source (`"pilot:<run>-packed tokens/comment ÷ single"`). `sample design-v2` accepts the same flag.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 17.3: Streaming packed screen
- [ ] **Step 1: Test** with the mock and a synthetic snapshot of 1,000 eligible comments:
  - `screen_sample(sample_id, run_id, k=5, budget="screen", rpm=1000, chunk=200, yes=True)` sorts the sample's comment IDs ascending and packs them deterministically in consecutive groups of k (the last group may be smaller). It loads items chunk by chunk with `load_items` and dispatches through `run_batch` with `packed_question_set(k)`.
  - It writes `packed_map.parquet` incrementally, one part per chunk, never rewriting earlier parts.
  - An interrupted run (raise after the 3rd chunk) resumes: `run_batch` skips completed packed items, and the final answers cover every sampled comment exactly once.
  - It prints the estimate first and dispatches only with `yes=True`.
  - It prints progress every chunk: comments done, calls, calculated USD, calls per minute, ETA.
- [ ] **Step 2: Fail. Step 3: Implement** in `screen/run.py`, reusing `atlas.pilot.packed.packed_items` and `packed_question_set`. **Step 4: Pass. Step 5: Commit and push.**

### Task 17.4: Per-comment table
- [ ] **Step 1: Test** `build_screen_table(run_id)` reads the answers and the packed map parts, unpacks with `atlas.pilot.packed.unpack_answers`, and joins the sample (stratum, weight, story_id, `contracts.half_of`). It writes `runs/<run>/screen_by_comment.parquet` with columns `comment_id, story_id, stratum, weight, half, firsthand_p, packed_id, slot, model_returned, request_id`. It raises if any sampled comment lacks an answer or appears twice.
- [ ] **Step 2: Fail. Step 3: Implement** in `screen/unpack.py`. **Step 4: Pass. Step 5: Commit and push.**

### Task 17.5: CLI
- [ ] `screen/cli.py` `register(sub)`:
  - `screen run --sample <id> --run <id> [--k 5] [--rpm 1000] [--chunk 5000] [--budget screen] [--yes]`
  - `screen table --run <id>`
- [ ] Add the row `screen run`, `screen table` (L17) to the AGENTS.md command table (allowed for this lane).
- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

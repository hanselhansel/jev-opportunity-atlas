# L22: Turn the main session's one-off scripts into tested, reproducible commands

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l22-productionize-main-run

**Goal:** Four steps of the real run were executed by the main session with scratch scripts. A stranger replaying this public repo must be able to rerun them from committed, tested commands that give the same output. Reference copies of the scripts are at `/Users/hansel/.codex/devin-runs/refs/l22/` (read them; do not import from there). Port their exact logic into the package.

**The four steps:**
1. `draw_main.py`: main breadth sample `main-20260930b`.
   - Pools pilot firsthand rates (cutoff 0.7) and costs across the two half-years.
   - Allocates on pooled strata with `allocate_by_yield`, then splits each pooled allocation across H1 and H2 in proportion to N.
   - Allocation budget `$6.64` at cost scale `0.424`; seed `20260930`.
   - The superseded first draw `main-20260930` used a $7.50 target and is kept but never screened.
2. `facets_phase2.py`: two-phase facet sample `main-facets-20260930`.
   - Positives at `firsthand_p >= 0.7`: 28,000. Below-cutoff checks: 2,000.
   - `n2_h` is proportional to the phase-1 weighted count per v2 stratum.
   - Final weight is `w1 / p2`; seed `20260931`.
   - Runs `facets@2` in chunks at 1,000 requests per minute under budget `facets`.
3. `packed_calibration.py`: packed-screen answers for calibration comments not already in the packed experiment (run `pilot-20260929-packedcal`).
4. `measure_tokens.py`: token measurement of question sets on 3 synthetic comments under budget `smoke` (runs `measure-*`).

**Read first:**
- `AGENTS.md`
- the four reference scripts
- `src/atlas/sampling/design_v2.py`, `yield_alloc.py`, `cli.py`
- `src/atlas/screen/`
- `src/atlas/pilot/packed.py`, `stages.py`
- `src/atlas/inference/runner.py`, `estimate.py`
- `docs/measurements/2026-09-28-token-costs.md`

**Files you own:**
- `src/atlas/sampling/pooled.py`
- `src/atlas/facets/__init__.py`, `src/atlas/facets/phase2.py`, `src/atlas/facets/cli.py` (the main session registers `atlas.facets.cli` and creates `tests/facets/__init__.py`)
- `src/atlas/pilot/packed_cal.py`
- `src/atlas/inference/measure.py`
- appended subcommands in `src/atlas/sampling/cli.py`, `src/atlas/pilot/cli.py`, and `src/atlas/inference/cli.py`
- `tests/sampling/test_pooled.py`, `tests/facets/test_phase2.py`, `tests/pilot/test_packed_cal.py`, `tests/inference/test_measure.py`
- the AGENTS.md command-table rows for the new commands (allowed)
- `docs/runbook-main-run.md`

### Task 22.1: Pooled, time-balanced allocation
- [ ] **Step 1: Test** with a synthetic frame and pilot observations:
  - `pooled_allocation(N, pilot_obs_p, pilot_obs_c, budget_tokens, floor_rate, cost_scale)` gives both halves of each pooled stratum the same sampling rate (within rounding);
  - thin pooled cells borrow from `pain|lbin|`, then `pain|`, then all, exactly as in the reference;
  - total expected tokens stay within 0.1% of the budget.

  Also test that the H1/H2 imbalance caused by alphabetical greedy fill in plain `allocate_by_yield` does not occur.
- [ ] **Step 2: Fail. Step 3: Implement** in `sampling/pooled.py`. Add `sample draw-pooled --pilot-run --budget-usd --cost-scale --cutoff --seed --sample-id` that writes the sample and a manifest with the same design block as the reference.
- [ ] **Step 4:** A test runs the command twice with the same inputs and gets byte-identical sample files. **Step 5: Commit and push.**

### Task 22.2: Two-phase facet sample and run
- [ ] **Step 1: Test** with a synthetic `screen_by_comment.parquet`:
  - `draw_phase2(...)` reproduces the reference allocation;
  - every row has `w1`, `p2`, `weight == w1 / p2`, and `phase` in {pos, neg};
  - the same seed gives the same IDs.

  With the mock, `run_phase2(...)` processes chunks, resumes after an interrupt, respects `rpm`, and prints an estimate before dispatching only with `yes=True`.
- [ ] **Step 2: Fail. Step 3: Implement** in `facets/phase2.py`, with commands `facets draw`, `facets estimate`, `facets run`. **Step 4: Pass. Step 5: Commit and push.**

### Task 22.3: Packed calibration and token measurement as commands
- [ ] `pilot packed-cal --run <pilot> [--yes]` (from `packed_calibration.py`, with its fixed map-format bug: the packed map is long-format `packed_id, slot, comment_id`).
- [ ] `jev measure --sets screen@1,facets@1 [--yes]` (from `measure_tokens.py`), printing the token table.
- [ ] Tests use the mock. Commit and push.

### Task 22.4: Runbook
- [ ] Write `docs/runbook-main-run.md`: the exact command sequence that produced the main run, in order, with each command's budget, run ID, and expected output shape:
  - snapshot build and verify
  - pilot draw, screen, facets, packed, injected, gold, report
  - packed-cal
  - `sample draw-pooled` (both the superseded and the used draw, with the reason)
  - `screen run` and `screen table`
  - facets draw and run
  - cards assign, verify, merge, planted
  - `benchmark run`
  - `site data`, `x charts`
  - `release pack` and `release pages`

  No HN text, no key. Commit and push.
- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

# L31: No silent budget stops, and honest cost estimates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l31-no-silent-budget-stops

**Goal:** In the main run, `cards merge --all-pairs` hit a budget cap before its first call. `run_batch` returned `stopped="budget"`, but `score_merges` ignored it, and the command printed `[]` ("no merges proposed") and exited 0. A skipped check looked like a clean result. Also, estimates were low against real ledger cost: `cards verify` by 2.0 times, card-level assign calls by about 1.3 to 1.4 times.

**Read first:** `AGENTS.md`, `src/atlas/inference/runner.py` (the `stopped` field), `src/atlas/cards/engine/cli.py`, `cli_extra.py`, `merge.py`, `verify.py`, `assign.py`, `induce.py`, `src/atlas/cards/replies_run.py`, `src/atlas/robustness/cli.py`, `src/atlas/facets/phase2.py`, `src/atlas/screen/run.py`, `src/atlas/inference/estimate.py`.

**Files you own:** the modules above (only the changes below), plus `tests/cards/engine/test_budget_stop.py` and `tests/inference/test_estimate_calibration.py`.

### Task 31.1: Fail loudly
- [ ] **Test** with the mock transport and a budget cap too small for one call. `cards assign`, `induce`, `merge`, `verify`, `planted`, `replies`, `robust assign-paraphrase`, `facets run`, and `screen run` each:
  - exit non-zero;
  - print a JSON line `{"stopped": "budget", "budget": <name>, "completed": <n>, "remaining": <n>}` to stderr;
  - never print a result that reads as complete. For `merge`, that means no proposals output and no `merge-<v>.json` written unless every pair was scored.
- [ ] **Implement** by threading the `run_batch` result up through each engine function. The simplest path is an exception class `BudgetStopped` raised when `stopped` is set, caught in the CLI layer. Commit, push.

### Task 31.2: Calibrated estimates
- [ ] The card commands estimate tokens as `len(canonical_json(body)) / 3.2`. Real billed input tokens are larger. Add `estimate_multiplier` per command family in `configs/prices.toml` under a new `[estimate_calibration]` table: `assign_card = 1.4`, `assign_group = 1.1`, `verify = 2.0`, `merge = 1.3`, `replies = 1.3`, `facets = 1.15`, `screen = 1.0`.
  - Apply it in every printed estimate.
  - Record the raw and calibrated figures side by side in the estimate JSON (`estimated_usd_raw`, `estimated_usd`, `calibration`).
- [ ] **Test** the multiplier is applied and the raw figure kept. Commit, push. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

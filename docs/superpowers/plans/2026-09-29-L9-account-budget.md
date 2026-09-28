# L9: Account-wide $25 cap, cost estimates before dispatch, and credit reconciliation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l9-account-budget

**Goal:** No combination of runs can ever spend more than the $25 of TypeSafe credit Hansel has. Every paid command shows its estimated cost before it runs. Calculated cost can be reconciled against the credit balance Hansel reads from the TypeSafe console.

**Architecture:** Extend `atlas.inference.budget` with an account layer. `BudgetGuard.for_budget(name, ...)` also takes an account lock and checks the account total (`account_total` in `configs/budgets.toml`) across every run of every budget name. The effective headroom is `min(name_cap - name_committed, account_total - account_committed)`. Add a token estimator calibrated from ledgers, a per-question-set parent limit, and a balance log.

**Read first:** `AGENTS.md`, `src/atlas/inference/budget.py`, `ledger.py`, `runner.py`, `questions.py`, `cli.py`, `configs/budgets.toml`, `docs/measurements/2026-09-28-token-costs.md`.

**Files you own:**
- `src/atlas/inference/budget.py`, `src/atlas/inference/estimate.py` (new), `src/atlas/inference/balance.py` (new), `src/atlas/inference/cli.py` (append subcommands)
- `tests/inference/test_account_budget.py`, `tests/inference/test_estimate.py`, `tests/inference/test_balance.py`

---

### Task 9.1: Account-wide cap

- [ ] **Step 1: Test**
  - Two runs under different budget names (`pilot`, then `screen`) with `account_total = 0.001`. The second run's guard sees the first run's spend, and `reserve` raises `BudgetExceeded` once the account total would be passed, even though the `screen` cap is not reached.
  - Unknown charges from any budget count toward the account.
  - `for_budget` holds both `runs/.budget-<name>.lock` and `runs/.budget-account.lock`; a second process taking any budget raises `BudgetLocked` while the first holds the account lock (only one paid run at a time).
  - The error message states name cap, name committed, account total, account committed, and the resume command.
- [ ] **Step 2: Fail. Step 3: Implement.** `for_budget` scans all `runs/*/run_manifest.json` once, summing per name and overall. Read `account_total` from `configs/budgets.toml` inside `for_budget` (new optional parameter `account_total: float | None`; `None` means read the config). Rebuilt unknown attempts keep the flat worst case (`worst_case_tokens_per_unknown_attempt`); state this limitation in the docstring. `LEDGER_FIELDS` does not change.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 9.2: Calibrated cost estimates before dispatch

- [ ] **Step 1: Test** `estimate_cost(items, qs, model, calibration)` returns `calls`, `est_input_tokens`, `est_usd`, and `method`. `calibration` is fitted by `fit_calibration(ledger_paths)`, a least-squares fit of reported `input_tokens` on request-body bytes per question set, with a fallback of bytes / 3.2 when no ledger exists. On the measured runs in `docs/measurements/2026-09-28-token-costs.md`, the calibrated estimate is within 10% of reported tokens (build a synthetic ledger in the test with those numbers).
- [ ] **Step 2: Fail. Step 3: Implement** in `estimate.py`, reusing `build_state`, `questions_for`, and `canonical_json` to size bodies exactly as the runner will send them.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 9.3: (moved to L11, which owns `runner.py`)

### Task 9.4: Credit balance log and reconciliation

- [ ] **Step 1: Test**
  - `record_balance(usd, note)` appends `{at, usd, note}` to `runs/balance.jsonl`.
  - `reconcile()` pairs consecutive balance records and, for each interval, sums calculated cost and unknown attempts from ledger rows whose `ended_at` falls in the interval. It reports `provider_delta`, `calculated`, `difference`, and `status`:
    - `reconciled` when the difference is within $0.01 (console precision) and unknown attempts are 0;
    - `explained_by_unknown` when the difference is within the unknown worst case;
    - `unexplained` otherwise.
- [ ] **Step 2: Fail. Step 3: Implement** in `balance.py`. **Step 4: Pass. Step 5: Commit and push.**

### Task 9.5: CLI

- [ ] Append to `inference/cli.py` under the existing `jev` command:
  - `jev budget`: per-name and account committed, reserved, unknown, remaining.
  - `jev estimate --set <name@version> --items <parquet>`: calls, tokens, USD, and the share of the remaining account.
  - `jev balance record <usd> [--note]`: Hansel reads the TypeSafe console and types the value.
  - `jev balance reconcile`
- [ ] Tests for `jev budget` and `jev balance` on temp directories (monkeypatch `atlas.paths`).
- [ ] `scripts/verify.sh` must print `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

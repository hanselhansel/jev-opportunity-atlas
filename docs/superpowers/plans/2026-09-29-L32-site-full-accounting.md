# L32: Full-spend run accounting, the human audit, and finding domains in the site data

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l32-site-full-accounting

**Goal:** The real site build has three gaps.
1. The `runs` table, and so the X cost chart, holds only the three runs passed to `site data` ($0.74 for cards), not the whole project (about $21.7 across 23 ledgers).
2. The `quality` table lacks Hansel's blind assignment audit. Its report is `runs/pilot-20260929-cards/eval_assignment_audit.json`, which is not one of the passed runs.
3. `findings.domain` is null.

**Read first:** `AGENTS.md`, `src/atlas/sitedata/build.py`, `build_quality.py`, `build_cards.py`, `cli.py`, `xspecs.py`, `configs/run_phases.toml`, `src/atlas/inference/ledger.py`.

**Files you own:** `src/atlas/sitedata/build.py`, `build_quality.py`, `build_cards.py`, `cli.py`, `xspecs.py`, and tests under `tests/sitedata/`.

### Task 32.1: Runs from a phase map
- [ ] **Test:** `site data --run-phases <toml>` builds `runs` from every key in `[runs]`.
  - A key `a/b` reads `runs/a/b/ledger.jsonl`, and its `run_id` is written as `a/b`.
  - `phase` comes from the value.
  - A key whose ledger is missing is an error naming the key.
  - Without the flag, behavior is unchanged.
  - `meta` gains `total_calculated_usd` (sum over rows) and `total_calls`.
- [ ] Update the X cost chart spec to use the sum over all rows and to break it down by phase. Commit, push.

### Task 32.2: Audit runs
- [ ] `site data --audit-run <run>` (repeatable) adds those runs' `eval_*.json` reports to `quality`, including the `random` group rows (system `random_card`). Test with a synthetic report shaped like `runs/pilot-20260929-cards/eval_assignment_audit.json` (groups jev and random, lenient and strict precision with ci, n). Commit, push.

### Task 32.3: Finding domain
- [ ] `findings.domain` is the weighted modal facets `domain` choice among the card's comments (phase-2 weight). Ties break alphabetically. Test, commit, push.

- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

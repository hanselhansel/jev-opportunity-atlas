# L30: `cards induce --scope all`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l30-induce-scope-all

**Goal:** `cards induce` re-asks only residue rows at card level. That leaves base rows already on a base card unable to move to a card added in the new version, which biased some card shares in the main run: wave 1 went through t2 then induce, while wave 2 was assigned directly under t3. Add a scope option that re-asks the card level for every row with a real group, so that every row ends up with a card chosen from the full new card list.

**Read first:** `AGENTS.md`, `src/atlas/cards/engine/induce.py`, `src/atlas/cards/engine/cli_extra.py` (or wherever `induce` is registered), `tests/cards/engine/test_induce.py`.

**Files you own:** `src/atlas/cards/engine/induce.py`, the file that registers `cards induce`, `tests/cards/engine/test_induce.py`.

### Task 30.1
- [ ] **Test** `--scope all`:
  - every base row with a real group gets a card-level call under `assign-c@<new version>`, with its base group, and no group-level call;
  - group-none rows are carried unchanged;
  - `--scope residue` (the default) behaves exactly as today.
  - Sidecar: `scope`, plus a `changed_card` count (rows whose final card differs from the base card).
  - A rerun with a different scope into the same run directory resumes. Residue rows already answered are not re-sent; the question-set label is the same, so the done set covers them.
  - `--base-run` may be a run produced by `cards induce` or `cards combine`, provided its assignments carry `--base-version`.
  - Base version and new version may be equal (`t3` to `t3`) when the base run mixes paths; allow it only with `--scope all`, and then skip the superset check.
- [ ] **Implement,** commit, push. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

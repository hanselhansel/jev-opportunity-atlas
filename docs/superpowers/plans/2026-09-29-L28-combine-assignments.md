# L28: Combine assignment runs into one table

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l28-combine-assignments

**Goal:** The main run assigns wave-1 comments in one run (`main-cards-20260930-t3`, via `cards induce`) and wave-2 comments in another (a fresh `cards assign` under the same cardset version). Downstream commands (`site data`, `cards verify`, `cards merge`, `cards replies`, `robust compare-assign`) read one run. Build a command that combines several runs of the same taxonomy version into a new run directory.

**Read first:** `AGENTS.md`, `src/atlas/cards/engine/assign.py` (`load_assignments`, `write_assignments`, `AssignResult`, the meta sidecar), `src/atlas/cards/engine/induce.py`, `src/atlas/cards/engine/cli.py`.

**Files you own:** `src/atlas/cards/engine/combine.py` (new), `src/atlas/cards/engine/cli.py` (one subcommand), `tests/cards/engine/test_combine.py`, the AGENTS.md command-table row (allowed).

### Task 28.1: `cards combine`
- [ ] **Test** `combine(run_ids, version, out_run)` with synthetic runs:
  - it reads each run's `assignments-<version>.parquet` and meta sidecar through `load_assignments`;
  - it refuses overlapping `comment_id`s across runs, and any run whose rows carry a different `taxonomy_version`;
  - it writes `<out_run>/assignments-<version>.parquet` and the meta sidecar through `write_assignments`, with `run_id` re-stamped to `out_run` and rows sorted by `comment_id`;
  - it concatenates each input run's `pain.parquet` into `<out_run>/pain.parquet`, deduplicated by `comment_id`, and refuses if two runs disagree on a pain sentence;
  - it writes `<out_run>/combine-<version>.json` with the input run IDs, per-run row counts, and the sha256 of each input assignments file.
- [ ] **Test** that answers are not copied, and that `cards verify` and `cards replies` on the combined run still find what they need. If they read `answers/` from the run, add a `--source-runs` note to the sidecar and make `load_assignments` usage work; do not duplicate answer files. Report what you found in the PR body.
- [ ] **CLI:** `cards combine --runs a,b --version t3 --run <out>` (no Jev calls). Commit, push. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

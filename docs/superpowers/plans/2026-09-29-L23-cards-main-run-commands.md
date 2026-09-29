# L23: Card commands for the main run

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l23-cards-main-run

**Goal:** The main session ran the card steps with scratch scripts. Port them to tested commands, and add the two card steps that have logic but no command: the unsolved-replies check and all-pairs merge scoring. Reference scripts are in `/Users/hansel/.codex/devin-runs/refs/l23/` (read them; do not import from there).

**Read first:**
- `AGENTS.md`
- `src/atlas/cards/engine/cli.py`, `assign.py`, `merge.py`, `verify.py`
- `src/atlas/cards/replies.py`, `metrics.py`
- `src/atlas/inference/runner.py` (`RunContext.rpm`, `concurrency`)
- `src/atlas/facets/` if present on main
- `docs/superpowers/specs/2026-09-29-analysis-design.md` (steps 3 to 8)

**Files you own:**
- `src/atlas/cards/items.py` (new)
- `src/atlas/cards/engine/cli.py`
- `src/atlas/cards/replies_run.py` (new)
- `src/atlas/cards/engine/merge.py` (only the `all_pairs` option)
- `tests/cards/test_items.py`, `tests/cards/test_replies_run.py`, `tests/cards/engine/test_cli_flags.py`, `tests/cards/engine/test_merge_all_pairs.py` (create `__init__.py` files only where a test directory lacks one and it is not frozen)
- AGENTS.md command-table rows for new commands (allowed)

### Task 23.1: `cards items` and `cards draft-sample`
- [ ] **Test** with a synthetic facet sample, facet answers (`answers/part-*.parquet`, question set `facets@2`), and a synthetic snapshot:
  - `build_items(facets_run, sample_id, snapshot_id, account_types=("firsthand_account",))` returns rows `comment_id, pain_sentence, sentences, phase, half, weight`;
  - `pain_sentence` is `sentences[k]` for the answer choice `s<k>`, and rows with a missing or out-of-range choice are dropped and counted;
  - only rows whose `account_type` choice is in `account_types` are kept.
- [ ] **Test** `draft_sample(items, n, seed, half="explore", phase="pos")` draws without replacement with probability proportional to `weight`, using `np.random.default_rng(seed).choice(len(pool), n, replace=False, p=w / w.sum())` on the pool in `comment_id` order (exactly as the reference), and the same seed gives the same IDs.
- [ ] **Implement** in `cards/items.py`.
  - `cards items --facets-run --sample --snapshot --out <parquet>` writes `comment_id, pain_sentence, sentences` (the schema `cards assign --items` reads) plus a sidecar `<out>.meta.json` with counts per phase and account type.
  - `cards draft-sample --items --sample --n 1500 --seed 20261001 --out <tsv>` writes the drafting TSV. The TSV holds HN text, so refuse any `--out` that is not under `data/` (gitignored).
- [ ] Commit and push.

### Task 23.2: Rate and concurrency flags
- [ ] **Test** that `cards assign|merge|verify|planted|replies` accept `--rpm` (default 1000) and `--concurrency` (default 8), and that `_run_ctx` passes both into `RunContext`. Mock the transport; no network.
- [ ] Implement, commit, push.

### Task 23.3: All-pairs merge scoring
- [ ] **Test** `merge_pairs(cs, assignments, all_pairs=True)` returns every pair of active cards across all groups (n*(n-1)/2), sorted. The default stays unchanged.
- [ ] Add `cards merge --all-pairs`. Commit and push.

### Task 23.4: `cards replies`
- [ ] **Test** with a synthetic snapshot and a synthetic assignment run:
  - problems are assigned comments with `card_id` not `none` and `card_p >= 0.5`, optionally limited to the top `--top-cards N` cards by assigned count;
  - reply pairs come from `replies.reply_pairs(snapshot_dir, problem_ids, max_replies=5)`; items from `reply_items` and `followup_items` with the pain sentences from `<assign run>/pain.parquet`;
  - the command prints an estimate, runs only with `--yes`, under budget `replies`, and writes `<run>/replies/answers`, `<run>/replies/mapping.parquet`, and `<run>/replies/unsolved_by_problem.parquet` via `unsolved_by_problem`;
  - a rerun resumes (no duplicate paid calls in the mock).
- [ ] Implement in `cards/replies_run.py` plus the subcommand `cards replies --run <assign run> --version <t> --snapshot <id> [--top-cards N] [--max-replies 5] [--yes]`. Commit and push.

- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

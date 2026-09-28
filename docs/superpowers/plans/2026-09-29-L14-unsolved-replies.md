# L14: Is the problem already solved? (Jev reads the replies)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l14-unsolved-replies

**Goal:** For comments on the top need cards, check their direct replies: does any reply name an existing tool or approach that solves the author's problem, and does the author confirm or reject it? This separates met needs from unmet ones, the strongest "unmet need" signal besides workarounds.

**Architecture:** Replies are already in the snapshot: a reply is a comment whose `parent_id` is the problem comment, so no network is needed. New module `src/atlas/cards/replies.py` builds runner items with per-item `state` and `questions` (runner extension from L11 Task 11.1; if it is not merged yet, build the items and test them without running, and note it in the PR). One call per (problem, reply) pair, capped at the first 5 direct replies by time.

**Read first:** `AGENTS.md`, `src/atlas/contracts.py`, `src/atlas/inference/runner.py`, `src/atlas/sources/items.py`, `docs/superpowers/specs/2026-09-29-analysis-design.md` step 8.

**Files you own:** `src/atlas/cards/replies.py`, `tests/cards/test_replies.py`.

### Task 14.1: Pair builder

- [ ] **Step 1: Test** with a synthetic snapshot (`comments.parquet` written in `tmp_path`, IDs 9_300_000_000+): `reply_pairs(snapshot_dir, problem_ids, max_replies=5)` returns, for each problem comment, up to 5 direct replies ordered by `time`, excluding dead, deleted, and empty ones, and excluding replies written by the problem's own author (keep those in a separate `author_followups` list for the next task).
- [ ] **Step 2: Fail. Step 3: Implement** with DuckDB. **Step 4: Pass. Step 5: Commit and push.**

### Task 14.2: Items and questions

- [ ] **Step 1: Test** `reply_items(pairs, pain_sentences)` returns runner items with `state = {"problem": pain_sentence, "reply": reply_text[:1200]}` and two questions:
  - `names_solution` (noul): "Does `reply` name an existing tool, product, or approach that would solve `problem`?"
  - `solution_kind` (choice): `commercial_product`, `open_source_tool`, `built_in_feature`, `process_or_workaround`, `none`.

  Separately, `followup_items(author_followups, pain_sentences)` asks `author_says_solved` (choice: `solved`, `still_unsolved`, `unclear`) on the author's own follow-ups. The `comment_id` of each item is the reply's ID; the problem ID travels in item metadata and is written to an output mapping file.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 14.3: Unsolved share per problem

- [ ] **Step 1: Test** `unsolved_by_problem(answers, mapping, threshold=0.5)` returns per problem comment:
  - `any_solution_named`
  - `solution_kinds`
  - `author_says_solved`
  - `unsolved`: true when no reply names a solution, or the author says it is still unsolved

  The output joins into L13's `card_metrics` through the optional `replies` argument (column `unsolved`).
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**
- [ ] `scripts/verify.sh` must print `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

# S5: Named fixes (dictionary match, then Jev confirms)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first. Only the main session runs Jev with `--yes`.

Branch: feat/s5-solutions

**Goal:**
- Find where problems and their replies name a product or company from `configs/tools.v1.yaml`.
- Ask Jev one yes/no question per reply hit.
- Write per-tool and per-card tallies to `story.json`.

**Read first:**
- the master plan
- `src/atlas/cards/replies.py` (`reply_pairs`), `src/atlas/cards/replies_run.py`
- `src/atlas/inference/runner.py` (per-item `state` and `questions`)
- `src/atlas/cards/engine/cli.py` (the `--rpm` and `--concurrency` pattern and the budget stop)
- `configs/tools.v1.yaml` (main session, M1)

**Files you own:** `src/atlas/solutions/__init__.py`, `match.py`, `confirm.py`, `tally.py`, `cli.py`; `tests/solutions/test_match.py`, `test_confirm.py`, `test_tally.py`; the AGENTS.md rows.

**Interfaces:**
- `match.load_tools(path) -> list[Tool]`, where `Tool` has `name, aliases, category`.
- `match.find_mentions(text: str, tools) -> set[str]`:
  - case-insensitive whole-word match on name and aliases;
  - an alias of 3 characters or fewer matches only case-sensitively.
- `confirm.confirm_items(hits) -> list[runner item]`:
  - one item per (reply_id, tool);
  - state `{problem: <pain sentence>, reply: <reply text, first 1200 chars>, tool: <name>}`;
  - question `recommends: noul "Does \`reply\` recommend \`tool\` as a fix for \`problem\`?"`.
- `tally.tally(mentions, confirmed) -> (tools_rows, card_tools)`, matching the contract's `tools` and `cards[].tools`.
- **CLI:** `atlas solutions run --assign-run main-cards-final2-t3 --snapshot <id> --top-cards 40 [--rpm 1000] [--concurrency 8] [--yes]`.
  - It prints an estimate, then runs under budget `solutions`.
  - It writes `runs/<assign run>/solutions/{mentions.parquet, answers/, tallies.json}`.
  - Parquet holds IDs and tool names only.
  - On a budget stop it exits non-zero with the stop JSON.
- `atlas story data --with tools` reads `tallies.json` and merges `tools` and `cards[].tools`.

## Task 1: Matching
- [ ] **Test** `test_alias_whole_word`: "use AWS" matches `aws`; "laws" does not.
- [ ] **Test** `test_short_alias_case_sensitive`: `Go` the language matches only as "Go", not "go".
- [ ] Implement, pass, commit.

## Task 2: Confirm and tally
- A mention in the problem comment itself counts as `complaint` (no Jev call).
- A mention in a reply counts as `fix` only when Jev says `recommends >= 0.5`.
- `threads` counts distinct `story_id`.
- `fix_share = fix_threads / (fix_threads + complaint_threads)`, with a thread bootstrap interval (R = 1000, seed 0).
- A tool in fewer than 10 threads is kept in tallies but marked `sparse`.

- [ ] **Test** `test_problem_mention_is_complaint_no_call` (asserted on the mock transport).
- [ ] **Test** `test_rerun_resumes_no_duplicate_calls`.
- [ ] **Test** `test_budget_stop_exits_nonzero`.
- [ ] Implement, wire the CLI and `story data --with tools`, pass, commit. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

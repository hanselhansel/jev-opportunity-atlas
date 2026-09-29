# S6: Builders on Show HN (sample, then assign to cards)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first. Only the main session runs Jev with `--yes`.

Branch: feat/s6-builders

**Goal:**
- Sample 8,000 of the 46,070 in-window Show HN stories.
- Assign each to the t3 cards with launch-framed instructions.
- Write builder shares and the builder-to-complaint ratio per card.

**Read first:** the master plan; `src/atlas/cards/engine/assign.py` (`assign` with `group_instructions` and `card_instructions`); `src/atlas/sources/items.py`; the snapshot `stories.parquet` (`id, title, text_norm, in_window, thread_type, time`).

**Files you own:** `src/atlas/builders/__init__.py`, `sample.py`, `run.py`, `shares.py`, `cli.py`; `tests/builders/test_sample.py`, `test_run.py`, `test_shares.py`; the AGENTS.md rows.

**Interfaces:**
- `sample.draw_launches(snapshot_id, n=8000, seed=20261006) -> pa.Table`.
  - Population: `in_window` and title starting with "Show HN" (case-insensitive).
  - Stratified SRSWOR by month (P01 to P12), proportional to month size.
  - Columns `story_id, period, weight`, where weight = N_month / n_month.
  - Writes `data/samples/builders-20261006.parquet` and a manifest.
- `run.launch_items(table, snapshot_id) -> list[dict]`:
  - `comment_id = story_id`;
  - `pain_sentence` = the title with the "Show HN:" prefix stripped;
  - `sentences` = [title] + the first 3 sentences of `text_norm` (at most 300 characters total).
- **Instructions:**
  - `GROUP = "Which group of needs does the product in \`problem\` address? \`sentences\` describes it."`
  - `CARD = "Which need does the product in \`problem\` address?"`
- **CLI:**
  - `atlas builders draw [--n 8000] [--seed 20261006]`;
  - `atlas builders run --cardset main --version t3 --run builders-20261006 [--rpm 1000] [--yes]` prints an estimate, then runs `assign` with the instructions above under budget `builders`, and exits non-zero on a budget stop.
- `shares.builder_shares(assign_rows, sample, story_cards) -> (builders, per_card)`:
  - `launch_share` = the weighted share of launches assigned to the card (card_p >= 0.5), bootstrap by month strata with each story its own cluster (R = 1000, seed 0);
  - `ratio` = launch_share / complaint share, with the interval from both replicate sets (the complaint share replicates come from S1 `boot`);
  - `match_rate` = the share of launches assigned to any card.
- `atlas story data --with builders` merges the results.

## Task 1: Sample
- [ ] **Test** `test_month_proportional`: month sample sizes equal round(n × N_m / N) and the weights sum to N.
- [ ] **Test** `test_only_show_hn_in_window`.
- [ ] Implement, pass, commit.

## Task 2: Assign and shares
- [ ] **Test** `test_uses_launch_instructions`: the mock transport sees the launch instruction text at both levels.
- [ ] **Test** `test_zero_launch_card`: a card with no sampled launch gets `launch_share.est = 0`, `sparse = true`, and ratio `est = 0` with the upper bound from the replicates.
- [ ] **Test** `test_budget_stop_exits_nonzero`.
- [ ] Implement, wire the CLI and `story data --with builders`, pass, commit. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

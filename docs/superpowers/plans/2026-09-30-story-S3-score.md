# S3: Opportunity score, rank stability, bundles, edges, replies join

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first.

Branch: feat/s3-story-score

**Goal:** Add `cards[].unsolved`, `cards[].score`, `score_presets`, `bundles`, and `edges`.

**Read first:** the master plan; S1's `frame.py`, `boot.py`, `io.py`; `src/atlas/cards/replies.py` (`unsolved_by_problem` columns); `runs/main-cards-final2-t3/merge-t3.json` (its shape: `scored:[{card_a, card_b, expected, ...}]`).

**Files you own:** `src/atlas/story/score.py`, `bundles.py`, `unsolved.py`; `tests/story/test_score.py`, `test_bundles.py`, `test_unsolved.py`; a `--with score` step in `story/cli.py`.

**Interfaces:**
- **Consumes:** S1's frame and bootstrap. `replies/unsolved_by_problem.parquet` from the assign run. The merge JSON. S2's `coping.commercial` and `quality.severe3`, when present in `story.json`. S6's `builders.ratio`, when present.
- **Produces:**
  - `unsolved.card_unsolved(frame, replies_parquet) -> {card: {unsolved, author_solved} | None}`;
  - `score.build_scores(story: dict, reps) -> (cards_score, presets)`;
  - `bundles.build_bundles(merge_json, story) -> (bundles, edges)`.

## Task 1: Unsolved join
- A card gets values only when at least 30 of its problems have reply answers. Otherwise it is `None`.
- `unsolved` is the weighted share with `unsolved == True`.
- `author_solved` is the weighted share with `author_says_solved == True`.

- [ ] **Test** `test_card_without_replies_is_none`.
- [ ] **Test** `test_unsolved_weighted`: two problems with weights 3 and 1, one unsolved (weight 3), give 0.75.
- [ ] Implement, pass, commit.

## Task 2: Score and rank stability
**Components:**
- `share`, `growth = change.shrunk`, `paid = coping.commercial`, `unsolved`, `severe = quality.severe3`;
- `underbuilt = -log(builders.ratio)` when present, else null.

**Scoring:**
- Each component becomes a percentile rank among cards with at least 50 problems. Null stays null.
- The score is the weighted mean over non-null components with renormalized weights.
- **Presets:**
  - `balanced`: all 1;
  - `growth`: growth 3, share 1, others 0.5;
  - `paid_pain`: paid 3, severe 2, unsolved 2, others 0.5;
  - `underbuilt`: underbuilt 3, unsolved 2, others 0.5.
- **`rank_quantiles`:**
  - recompute the balanced score for each of the R bootstrap replicates of share, growth, paid, and severe, holding the other components fixed;
  - rank within each replicate;
  - store the 20 ventile ranks (5%, 10%, …, 100%).

- [ ] **Test** `test_null_component_renormalizes`: a card with `unsolved = None` is scored on the rest. Its score equals the manual mean.
- [ ] **Test** `test_all_zero_weights_equal`: the preset math refuses all-zero weights and falls back to equal weights.
- [ ] **Test** `test_rank_quantiles_monotone`: the 20 values are non-decreasing.
- [ ] Implement, pass, commit.

## Task 3: Bundles and edges
- **Edges:**
  - for each card, the 8 highest `expected` merge scores with another card;
  - keep `score >= 1.0`;
  - deduplicate undirected pairs.
- **Clustering:**
  - distance = `2 - expected`;
  - scipy average-linkage over all 150 cards;
  - cut at distances 0.6, 0.8, and 1.0.
- **Bundles:**
  - clusters of 3 to 12 cards at the 0.8 cut;
  - `persistence` = the share of the other two cuts in which the same card set (Jaccard >= 0.7) exists;
  - `share` = the summed card share, with the interval from joint replicates;
  - `groups_spanned` = the number of distinct groups among members.

- [ ] **Test** `test_bundle_persistence_one_for_tight_clique`: four cards with mutual score 2.0 and 0 elsewhere give persistence 1.0.
- [ ] Implement, wire `story data --with score`, pass, commit. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

## Amendments

- **A1 (review of S6):** `src/atlas/builders/cli.py::_complaint_reps` selects `fr[fr["firsthand"]]`. That includes below-cutoff `neg` rows with very large weights. It must select `fr[(fr["phase"] == "pos") & fr["firsthand"]]`, the population in the master plan.
  - This lane owns that one-line fix.
  - Add `tests/builders/test_complaint_population.py`: a synthetic world where a heavy `neg` firsthand row on card X must not change X's complaint share.

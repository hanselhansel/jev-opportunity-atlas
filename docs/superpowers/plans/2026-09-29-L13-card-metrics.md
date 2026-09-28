# L13: Need-card metrics, convergence, and ranking

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l13-card-metrics

**Goal:** Turn Jev's card assignments and facet answers into per-card evidence (who, where, when, how painful, how unsolved), a convergence view (problem × domain × role), and a transparent ranking whose weights anyone can change, computed separately on the explore and confirm halves.

**Architecture:** New package `src/atlas/cards/` with pure functions over pyarrow or pandas-free numpy/duckdb tables. Inputs follow contracts: `ASSIGNMENTS`, `ANSWERS` (long format; facet question ids from `configs/questions/deep.v0.json` such as `workaround`, `paid`, `switched`, `abandoned`, `resolution`, `user_role`, `specificity`, plus `domain` from `screen.v0.json`), `COMMENTS` (author, story_id, period), `SAMPLE` (weight), and `contracts.half_of`. Ranking weights live in `configs/ranking.toml`. No Jev calls in this lane.

**Read first:** `AGENTS.md`, `src/atlas/contracts.py`, `docs/superpowers/specs/2026-09-29-analysis-design.md` sections 4 (steps 8 to 10), 5, and 8.

**Files you own:**
- `src/atlas/cards/__init__.py`, `src/atlas/cards/metrics.py`, `src/atlas/cards/rank.py`, `src/atlas/cards/convergence.py`
- `configs/ranking.toml`, `configs/finding_criteria.toml`
- `tests/cards/__init__.py` (create), `tests/cards/test_metrics.py`, `tests/cards/test_rank.py`, `tests/cards/test_convergence.py`

---

### Task 13.1: Per-card evidence metrics

- [ ] **Step 1: Test** (build synthetic tables in the test; IDs 9_000_000_000+)
  - `card_metrics(assignments, answers, comments, sample, author_cap=3, min_card_p=0.5)` returns one row per card with:
    - `n_comments` and `n_comments_capped` (at most `author_cap` per author)
    - `n_authors`, `n_threads`, `n_periods`, `n_halfyears`, `n_domains`, `n_roles`
    - `max_thread_share` and `max_author_share`
    - `workaround_rate`, `paid_rate`, `switched_rate`, `abandoned_rate`, `unresolved_rate`, `mean_specificity`
    - `weighted_n` (sum of sample weights)
    - `first_period`, `last_period`
  - Assert a hand-computed case:
    - 6 comments by 4 authors in 3 threads, one author with 3 comments, and `author_cap=2` gives `n_comments_capped == 5`.
    - One thread holding 3 of 6 gives `max_thread_share == 0.5`.
    - Rates use facet probabilities thresholded at 0.5, a per-facet threshold dict that defaults to 0.5.
    - Comments with `card_p < min_card_p` or `card_id in {"none", None}` are excluded.
- [ ] **Step 2: Fail. Step 3: Implement** with DuckDB over Arrow tables (fast at 50k rows). Unsolved share comes later from replies; include a nullable `unsolved_rate` column filled from an optional `replies` table argument.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 13.2: Convergence

- [ ] **Step 1: Test** `problem_domain_matrix(...)` returns a long table (`card_id`, `domain`, `n_authors`) and `convergence_index(card)` = exponential of the Shannon entropy of the card's domain distribution (effective number of domains). A card spread evenly over 4 domains scores 4.0; a card in one domain scores 1.0. Same for roles (`effective_roles`).
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 13.3: Transparent ranking

- [ ] **Step 1: Test**
  - `rank_cards(metrics, weights)` returns every component normalized to 0 to 1 (min-max across cards, stated in a docstring), the weighted sum, and the rank.
  - With all weights zero except `n_authors`, the order equals the order by `n_authors`.
  - Changing `configs/ranking.toml` weights changes the order; the output includes the weights used.
- [ ] **Step 2: Fail. Step 3: Implement.** `configs/ranking.toml` defaults (equal weights, documented):
  - `n_authors_capped`, `n_threads`, `n_periods`, `effective_domains`, `effective_roles`
  - `workaround_rate`, `commercial_rate` (max of paid, switched, abandoned)
  - `unresolved_rate`, `mean_specificity`
  - `max_thread_share` (negative weight)
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 13.4: Explore and confirm

- [ ] **Step 1: Test** `evaluate_criteria(metrics_explore, metrics_confirm, criteria)` with `configs/finding_criteria.toml` (pre-registered, from design section 8): `min_authors = 10`, `min_periods = 3`, `min_domains = 2`, `max_thread_share = 0.30`. A card passes only when it meets the criteria in both halves. Output columns: `passes_explore`, `passes_confirm`, `candidate` (both), and a `reasons` list for failures.
- [ ] **Step 2: Fail. Step 3: Implement.** `split_by_half(table)` uses `contracts.half_of(story_id)`.
- [ ] **Step 4: Pass. Step 5: Commit and push.**

### Task 13.5: Finish

- [ ] Docstrings state the estimands plainly: these are sample counts and rates (discovery metrics). Population prevalence claims use `atlas.estimation` (L12), not these numbers.
- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

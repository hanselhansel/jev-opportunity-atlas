# L24: Correct two-phase weights and card-share estimates in the site data

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l24-site-estimates

**Goal:** `atlas site data` must estimate from the real two-phase design, and it must publish the headline numbers the X thread needs: what share of firsthand problems falls in each need group and card, and whether that share moved between the two half-years.

**The design (read carefully):**
- Phase 1 is the screen sample (`data/samples/main-20260930b.parquet`). The screen run's `screen_by_comment.parquet` carries its weight `w1`, `stratum`, `half`, `story_id`, `firsthand_p`.
- Phase 2 is the facet sample (`data/samples/<facet sample>.parquet`, columns `comment_id, story_id, stratum, half, phase, w1, p2, weight, firsthand_p`). `phase` is `pos` (firsthand_p >= 0.7) or `neg` (a check sample below the cutoff). **`weight` = w1 / p2 is the only correct weight for any faceted or assigned comment.**
- A "firsthand problem" is a phase-2 row whose facets@2 `account_type` choice is `firsthand_account`.
- Population `screen_positive` uses `phase == pos` rows only. Population `all_firsthand` adds the `neg` rows (few rows with very large weights; a sensitivity check, never the headline).

**Current bugs to fix:**
- `sitedata/build_cards.py::_tables` builds `sample` from the screen weights (`ctx["screen"][cid]["weight"]`, which is w1). For faceted and assigned comments this must be the phase-2 `weight`.
- Card metrics, findings, and evidence mix `pos` and `neg` rows. They must use `screen_positive` only.

**Read first:**
- `AGENTS.md`
- `src/atlas/sitedata/build.py`, `build_cards.py`, `build_share.py`, `tables.py`, `fixtures.py`, `cli.py`
- `src/atlas/cards/metrics.py`, `rank.py`
- `src/atlas/estimation/ppi.py`, `robust.py`
- `docs/superpowers/specs/2026-09-29-analysis-design.md` (steps 9 and 10, section 5)

**Files you own:**
- `src/atlas/sitedata/build.py`, `build_cards.py`, `build_share.py`, `tables.py`, `fixtures.py`, `cli.py`
- `src/atlas/sitedata/build_card_share.py` (new)
- `tests/sitedata/` (new test files, and edits to existing ones the change requires)

### Task 24.1: Phase-2 weights and population filter
- [ ] **Test** with a synthetic world where phase-2 weights differ from w1 and some `neg` rows are assigned to cards:
  - card metrics, findings, and evidence use the phase-2 `weight`;
  - `neg` rows never enter them;
  - `domain_share` numerator and denominator both come from phase-2 `pos` rows weighted by `weight`, restricted to firsthand problems.
- [ ] **Implement:** `site data --facet-sample <id>` (required in real mode) and pass it through `build_site_data(..., facet_sample=...)`. Add `meta.facet_sample`. Commit and push.

### Task 24.2: `card_share` table
- [ ] **Test** the new table's rows:
  - `level` (group or card), `id`, `label`, `population` (screen_positive or all_firsthand), `bucket` (all, H1, H2, or H2_minus_H1);
  - `share`, `lo`, `hi`, `n_items`, `n_authors`, `p_adj`, `qualifier`.
- [ ] **Estimand:** the weighted share of firsthand problems assigned to the group or card (card_p >= 0.5; "none" counts in the denominator):
  - `sum(w * 1[assigned to x]) / sum(w)` over firsthand problems in the population and bucket.
  - H1 and H2 come from `period` (P01-P06 is H1, P07-P12 is H2).
  - `H2_minus_H1` is the difference.
- [ ] **Intervals:** a stratified thread bootstrap (strata = phase-2 `stratum`, clusters = `story_id`, 2,000 reps, seed 0), reusing `build_share.boot_ratio`.
  - For the difference, use the same bootstrap draws for both halves.
  - `p_adj` is `robust.bootstrap_pvalue` on the difference, BH-adjusted with `robust.benjamini_hochberg` across all rows of the same level and population. Null elsewhere.
- [ ] **Qualifier:** "as classified by Jev; assignment audited" on every row. A test asserts shares within a population and bucket sum to at most 1 per level, and that a card with every item in one thread gets a wide interval.
- [ ] **Implement** in `build_card_share.py`. Add `card_share` to `SITE_TABLES` and to the fixture builder, so fixture mode still builds. Commit and push.

### Task 24.3: Replies input
- [ ] `site data --replies-run <run>` reads `<run>/replies/unsolved_by_problem.parquet` and passes it as `replies` to `card_metrics`, so findings carry `unsolved_rate`. Without the flag, behavior is unchanged. Test, commit, push.

- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

# L29: Show card shares, trends, and robustness on the site and in X charts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l29-site-card-shares

**Goal:** L24 added the `card_share` table (group and card shares of firsthand problems, with H1, H2, and H2_minus_H1 rows, intervals, and BH-adjusted p). The site and X charts do not use it yet, and the X "change" chart still computes an unweighted half-year change from evidence rows. Also add a `robustness` table so the site shows how the headline moves under reworded questions.

**Read first:**
- `AGENTS.md`
- `src/atlas/sitedata/build.py`, `build_card_share.py`, `tables.py`, `fixtures.py`, `cli.py`, `xspecs.py`, `xcharts.py`
- `site/src/index.md`, `site/src/method.md`, `site/src/components/*.js`, `site/src/data/*.parquet.py`
- `src/atlas/robustness/compare.py` (the JSON shapes of `compare-screen` and `compare-assign`)

**Files you own:**
- `src/atlas/sitedata/build.py`, `tables.py`, `fixtures.py`, `cli.py`, `xspecs.py`, `xcharts.py`
- `src/atlas/sitedata/build_robustness.py` (new)
- `site/src/index.md`, `site/src/method.md`
- `site/src/data/card_share.parquet.py`, `site/src/data/robustness.parquet.py` (new)
- `site/src/components/chart.js` (only if a new chart type is needed)
- `tests/sitedata/` (new or updated tests)

### Task 29.1: `robustness` table
- [ ] `site data --robust-screen <json> --robust-assign <json>` (both optional) writes a `robustness` table: `check` (screen_wording or assign_wording), `run_id`, `metric`, `value`, `lo`, `hi`, `n`.
  - Screen metrics: `prevalence` per run with its interval, plus `agreement`, `kappa`, and `spearman` per paraphrase run.
  - Assign metrics: `group_agreement`, `card_agreement`, and `max_abs_share_diff`.
- [ ] Empty table when neither flag is given. Add to `SITE_TABLES` and fixtures. Test with synthetic JSON shaped exactly like `compare.py` output. Commit, push.

### Task 29.2: Site
- [ ] **Index page.** Add a "Where the problems are" section above the finding cards:
  - a group-share bar chart (population `screen_positive`, bucket `all`, share with interval bars, labels from the table);
  - a top-20 card-share chart;
  - a "What changed between halves" chart of `H2_minus_H1` for groups and for the top-20 cards, with intervals. Only rows with `p_adj < 0.05` are highlighted and labeled as changed; every other row is drawn muted with "no clear change".
  - Each chart carries its denominator and the qualifier from the table.
- [ ] **Method page.** Add a "Does the wording matter?" section from `robustness`:
  - the headline prevalence under each wording, with intervals, stated as a range;
  - the agreement numbers.
- [ ] Keep every existing element working in fixture mode. `npm run build` in `site/` must pass. Commit, push.

### Task 29.3: X charts
- [ ] In `xspecs.py`, add specs `group_share`, `card_share_top` (top 12 cards), and `card_change` (H2_minus_H1 for the top 12 cards by share, from `card_share`, highlighting `p_adj < 0.05`).
  - Replace the old `change` spec (the unweighted evidence-based one) with `card_change`.
  - Add `wording_range` (screen prevalence under each wording, from `robustness`).
- [ ] Every chart keeps the existing footer rules (denominator, n, run ID, qualifier). Tests render each spec to a 1600x900 PNG from fixture tables. Commit, push.
- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

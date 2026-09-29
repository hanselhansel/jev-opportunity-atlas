# L33: Chart presentation for X and the site

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l33-chart-presentation

**Goal:** The real X charts (see `atlas x charts --data site/data-real`) have presentation defects:
- long card statements used as row labels wrap into each other;
- titles overflow the 1600 px width;
- the card-change chart shows the 12 largest cards, which mostly did not move, instead of the cards that did;
- small shares round to "0%" or "1%";
- run IDs appear as bar labels.

Fix them with display-only labels, configured titles, and better selection.

**Read first:** `AGENTS.md`, `src/atlas/sitedata/xspecs.py`, `xcharts.py`, `build.py`, `build_card_share.py`, `configs/cards/main.t3.labels.yaml`, `configs/x_titles.toml`, `site/src/index.md`, `site/src/method.md`, `site/src/components/chart.js`.

**Files you own:**
- `src/atlas/sitedata/xspecs.py`, `xcharts.py`, `build.py` (label plumbing only), `build_card_share.py` (label column only), `tables.py` (only if a column is added)
- `site/src/index.md`, `site/src/method.md`, `site/src/components/chart.js`
- tests under `tests/sitedata/`

### Task 33.1: Short labels
- [ ] `site data` reads `configs/cards/<cardset>.<version>.labels.yaml` when present.
  - It adds a `short_label` column to `card_share`, and to `findings` as an extra field. Short labels are Claude-drafted display text, so add them to the approved-text exemption: exact match against the labels file.
  - Groups and cards without a short label fall back to the full text.
- [ ] Every X chart and site chart uses `short_label` for row and axis labels. Full statements stay in tooltips and tables. Test: fixture label files, and no label longer than 32 characters reaching a chart. Commit, push.

### Task 33.2: Titles and run labels
- [ ] `xspecs` reads `configs/x_titles.toml`: `[titles]` per chart id, with `{placeholders}` filled from the data.
  - Placeholders: `top_share`, `min_share`, `max_share`, `total_usd`, `total_calls`, `jev_precision`, `random_precision`.
  - Format: percent with one decimal when under 10%, otherwise whole; USD with two decimals; calls with thousands separators.
  - An unknown placeholder is an error.
- [ ] `[run_labels]` replace run IDs in bar labels.
- [ ] `xcharts` fits the title: wrap to at most 2 lines at the current size, and shrink the font in steps down to 70% if needed, so no title overflows 1600 px. Test with a very long title (measure the text extent with the renderer). Commit, push.

### Task 33.3: Better selection and formatting
- [ ] `card_change` shows the cards with `p_adj < 0.05` in the `H2_minus_H1` bucket (population `screen_positive`), sorted by change, up to 8 risers and 8 fallers.
  - If fewer than 4 qualify, fill with the largest absolute changes, drawn muted with "no clear change".
  - The same selection drives the site's "What changed" chart.
- [ ] Bar value labels use one decimal for values under 10%.
- [ ] Row spacing grows with the number of wrapped label lines so labels never overlap. Test: bounding boxes of adjacent row labels do not intersect.
- [ ] `npm run build` in `site/` passes. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

# L20: Site data from real runs, and X-ready chart exports

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l20-site-data-and-x

**Goal:**
1. Turn saved run outputs into the text-free site tables the static site reads (`atlas.sitedata.tables.SITE_TABLES`), with `meta.mode == "real"`.
2. Render X-ready PNG charts whose caveats are drawn inside the image, so a screenshot can never lose them.

No Jev calls; everything reads saved files.

**Read first:**
- `AGENTS.md`
- `src/atlas/sitedata/tables.py`
- `site/` (L6 build and `scripts/render-check.mjs`)
- `src/atlas/cards/metrics.py`, `rank.py`, `convergence.py`
- `src/atlas/estimation/ppi.py`, `src/atlas/screen/unpack.py`, `src/atlas/cards/engine/assign.py`
- `src/atlas/publication/export.py` (allowlist and text gate)
- `docs/superpowers/specs/2026-09-29-analysis-design.md` (sections 5, 8, 10, 11)

**Files you own:** `src/atlas/sitedata/build.py`, `src/atlas/sitedata/xcharts.py`, `src/atlas/sitedata/cli.py`, `tests/sitedata/test_build.py`, `tests/sitedata/test_xcharts.py`.

### Task 20.1: Build site tables from runs
- [ ] **Step 1: Test** with synthetic run directories (IDs 9_000_000_000+). `build_site_data(out_dir, snapshot_id, screen_run, facets_run, assign_run, taxonomy_version, label_sets)` writes every table in `SITE_TABLES`:
  - `meta`: mode `real`, snapshot, runs, window, built_at, code commit.
  - `coverage`: from the snapshot coverage.
  - `domain_share`: PPI-corrected when gold labels exist for that estimand, otherwise marked `badge=estimated` and `qualifier="as classified by Jev; unaudited"`.
  - `evidence`: IDs, labels, probabilities, `text_sha256`; no text.
  - `findings` and `finding_evidence`: from card metrics and ranking.
  - `runs`: from ledgers, with calculated USD, unknown attempts, p50 and p95, and wall time.
  - `quality`: from the audit evaluation and the synthetic benchmark, with a `system` column and a `label_set` of `synthetic` for benchmark rows.

  Every output passes `atlas.publication.export.text_gate`.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 20.2: X chart exports
- [ ] **Step 1: Test** `render_x_chart(spec, out_png)` writes a 1600×900 PNG using matplotlib (already installed through dependencies; if not, stop and report). The footer is drawn inside the image at no smaller than 32 px: source, window, n and denominator, lane, run ID, "as classified by Jev", and "HN comments only; not market demand". The title is a full sentence. The test reads the PNG size and checks the footer text through the spec's recorded footer string (not OCR).
- [ ] Chart types:
  - horizontal bar with intervals (top cards by distinct authors)
  - problem × domain convergence heat strip
  - half-year change dot plot with intervals
  - cost and time summary panel (calculated USD, calls, p50 latency, wall time)
  - Jev quality panel (audit precision vs random-card baseline; benchmark accuracy labeled "synthetic cases")
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 20.3: CLI
- [ ] Extend `sitedata/cli.py` `register(sub)` with `site data --out site/data-real ...` and `x charts --out exports/x/<date>/ ...`. Add the row to the AGENTS.md command table (allowed).
- [ ] `scripts/verify.sh` must print `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

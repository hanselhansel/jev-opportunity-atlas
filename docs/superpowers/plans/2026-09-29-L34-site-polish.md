# L34: Site polish from the real-data review

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l34-site-polish

**Goal:** Fix four defects found reviewing the real build (`atlas site data` then `atlas site build --data <abs path>/site/data-real --production --base /jev-opportunity-atlas/`).

**Read first:** `AGENTS.md`, `src/atlas/sitedata/*.py`, `site/src/*.md`, `site/src/components/*.js`, `site/package.json`, `src/atlas/sitedata/source.py`.

**Files you own:** those files, and tests under `tests/sitedata/`.

### Tasks
- [ ] **Footers name the right run.**
  - Card charts (group share, card share, card change, heat, bars) on the site and in X charts name the assignment run (`meta.assign_run`), not the screen run.
  - The quality chart names the audit runs for human-audit rows (store `run_id` on quality rows from `--audit-run`) and the benchmark run for synthetic rows.
  - Test each footer.
- [ ] **Finding cards on the index page:** show the short label as the heading and the full statement once below it, not twice. Add a short-label column where findings appear in tables.
- [ ] **Evidence page subtopic column:** show the card's short label, keep the card ID in a `title` attribute, and filter by card through the hash.
- [ ] **`atlas site build --data <relative path>`** fails because the prebuild step resolves the path from `site/`. Resolve `--data` to an absolute path in the CLI before invoking npm. Test.
- [ ] `npm run build` passes. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

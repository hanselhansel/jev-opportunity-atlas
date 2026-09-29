# L21: Release bundles, stranger replay, and Pages from a branch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l21-release-and-replay

**Goal:** A stranger can go from clone to charts in about 10 minutes without an API key, gh auth, or HN calls. They restore a small public release over plain HTTPS, verify the hashes, check every claim, and build the site. Publishing the site uses a `gh-pages` branch, because this project has no GitHub Actions.

**Read first:** `AGENTS.md`, `src/atlas/publication/export.py`, `allowlist.py`, `claims.py`, `cli.py`, `site/package.json`, `docs/superpowers/plans/2026-09-29-L5-publication.md` (tasks 5.2 and 5.3 were deferred to here), `docs/superpowers/specs/2026-09-29-analysis-design.md` (sections 9 and 12).

**Files you own:**
- `src/atlas/publication/restore.py`, `src/atlas/publication/rehydrate.py`, `src/atlas/publication/replay.py`, `src/atlas/publication/pages.py`
- additions to `src/atlas/publication/cli.py`
- `scripts/replay.sh`
- `tests/publication/test_restore.py`, `test_rehydrate.py`, `test_replay.py`, `test_pages.py`
- `docs/reproduce.md`

### Task 21.1: Restore over HTTPS and verify
- [ ] Follow L5 Task 5.2 (tests included there), with two changes:
  - Download assets with httpx from `https://github.com/<repo>/releases/download/<tag>/<asset>`, with `gh` optional.
  - Ship two bundles: `site-<tag>.tar.zst` (site tables, manifests, claims; tens of MB) and `full-<tag>.tar.zst` (answers, ledgers, samples, labels).

  `verify_release` checks hashes and `schema_version`.
- [ ] Commit and push.

### Task 21.2: Rehydrate text from the official API
- [ ] Follow L5 Task 5.3 (tests there). Reuse `atlas.sources.hn_api.fetch_item`, and normalize with `atlas.sources.htmltext.html_to_text`. Output goes only to `data/rehydrated/`.
- [ ] Commit and push.

### Task 21.3: Replay
- [ ] **Step 1: Test** `replay(release_dir)`: verify, then `claims check` on the release, then build the site data directory from the release, with no network calls (monkeypatch `httpx.AsyncClient.send` to fail). It returns pass or fail per claim.
- [ ] **Step 2:** `scripts/replay.sh <tag>` runs: `uv sync --no-default-groups`, restore the site bundle, replay, then (if node exists) `npm ci` and build in `site/`. It prints elapsed time.
- [ ] **Step 3:** `docs/reproduce.md` gives three tiers, each with exact commands and expected output:
  1. Claims only, in about 5 minutes.
  2. Site, in about 10 minutes.
  3. Full re-analysis from saved answers.
- [ ] Commit and push.

### Task 21.4: Pages from a branch
- [ ] **Step 1: Test** `publish_pages(dist_dir, dry_run=True)`:
  - refuses unless `meta.mode == "real"` and the text gate passes on `dist`'s data;
  - builds the commit for branch `gh-pages` in a temporary worktree, with a `.nojekyll` file;
  - scans with `secret_scan` and gitleaks;
  - returns the commit it would push.

  Real pushes happen only in the main session with `dry_run=False`.
- [ ] **Step 2: Implement** in `pages.py`, plus `release pages --dist site/dist [--push]`. **Step 3:** Add rows to the AGENTS.md command table (allowed). Commit and push.
- [ ] `scripts/verify.sh` must print `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

# S8b: Story data fixes from the real-data review

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first.

Branch: feat/s8b-story-data-fixes

**Goal:** Fix the data gaps found in the real build.

**Files you own:**
- `src/atlas/cards/engine/cli_extra.py` (or wherever `cards planted` lives), `src/atlas/story/method.py`, `src/atlas/story/core.py` (labels only), `src/atlas/story/check.py`
- `configs/run_phases.toml`, `configs/story_labels.toml` (new)
- tests under `tests/story/` and `tests/cards/`

## Findings
1. **Planted result is not saved.**
   - `cards planted` prints the recovery JSON but saves no file, so `method.quality.planted_recovery` is null.
   - Make `cards planted` also write `<run>/planted-<version>.json` with the printed result.
   - `method._planted_recovery` reads that file first and keeps its current recompute as the fallback.
   - Test both paths.
2. **The run list misses the story runs.** Add to `configs/run_phases.toml`:
   - `"main-cards-final2-t3/solutions" = "named fixes"`;
   - `"builders-20261006" = "builders"`.
   Also confirm `main-planted-t3` is listed (add `"main-planted-t3" = "checks"` if missing).
   Test that `method.total_usd` equals the sum over the listed ledgers.
3. **Human labels.**
   - Add `configs/story_labels.toml` with `[domains]` and `[roles]` tables mapping every facets@2 choice key to a short human label, for example `consumer_tech = "Consumer tech"`.
   - `core.build_core` writes `story["labels"] = {"domains": {...}, "roles": {...}}`.
   - `check.check_story` adds these label values to the allowed vocabulary.
   - Test that every domain and role ID in the story has a label.

- [ ] Implement with TDD. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

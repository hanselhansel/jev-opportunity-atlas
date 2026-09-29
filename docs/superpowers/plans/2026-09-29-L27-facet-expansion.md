# L27: Expand the phase-2 facet sample (second wave)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l27-facet-expansion

**Goal:** Hansel approved faceting about 50k more screen positives, so each need card has roughly 2.8 times more comments. The existing phase-2 sample `main-facets-20260930` (28,004 positives, 2,022 below-cutoff checks) must grow to a larger phase-2 sample that is still a valid stratified simple random sample, keeping every already-faceted comment. The paid runs happen only in the main session.

**Why this is valid:** within a stratum, an SRSWOR of n followed by an SRSWOR of m from the remaining units is an SRSWOR of n+m. So the expanded sample's phase-2 probability is `(n_old_h + m_h) / N_h` for every positive row in stratum h, and the final weight is `w1 / p2` as before.

**Read first:**
- `AGENTS.md`
- `src/atlas/facets/phase2.py` (`allocate_capped`, `draw_phase2`, `PHASE2_SCHEMA`), `src/atlas/facets/cli.py`
- `src/atlas/inference/runner.py` (done-set resume), and how `facets run` writes the run manifest
- `docs/runbook-main-run.md`

**Files you own:**
- `src/atlas/facets/expand.py` (new)
- `src/atlas/facets/cli.py` (one new subcommand; plus the resume fix below if needed)
- `src/atlas/facets/phase2.py` (only if `facets run` needs a change to resume on an expanded sample)
- `tests/facets/test_expand.py`
- `docs/runbook-main-run.md` (add the expansion step)
- the AGENTS.md command-table row (allowed)

### Task 27.1: `expand_phase2`
- [ ] **Test** with a synthetic `screen_by_comment.parquet` and a base sample made by `draw_phase2`:
  - `expand_phase2(screen_run, base_sample_id, new_sample_id, n_pos, seed)` recomputes `target_h = allocate_capped(wsum, sizes, n_pos)` over positives (`firsthand_p >= cutoff`, cutoff read from the base sample manifest), with `wsum` and `sizes` exactly as in `draw_phase2`;
  - `m_h = max(0, target_h - n_old_h)`, never dropping a base row;
  - added rows come from the stratum's not-yet-selected positives sorted by `comment_id`, via `rng.choice(len(remaining), m_h, replace=False)`, strata in sorted order, `rng = np.random.default_rng(seed)`;
  - every positive row in a stratum gets `p2 = (n_old_h + m_h) / N_h` and `weight = w1 / p2`;
  - `neg` rows are copied unchanged.
- [ ] **Output** is the base schema plus an int8 column `wave` (1 base, 2 added). Sample file plus a manifest: base sample id, seed, n_pos target, rows added per phase, and the design sentence above.
- [ ] **Test:**
  - the base IDs are a subset of the new IDs;
  - positive weights in each stratum sum to that stratum's phase-1 weighted positive count (within 1e-9 relative);
  - the same seed gives the same file;
  - an `n_pos` below the base count adds nothing;
  - the full real-scale property: adding rows never lowers any stratum's count.
- [ ] Commit and push.

### Task 27.2: CLI and resume
- [ ] `facets expand --screen-run --base-sample --sample-id --n-pos --seed` writes the new sample.
- [ ] **Test** that `facets run --sample <expanded> --run <existing run>` on the mock transport dispatches only the added comments: rows already in the run's done set are skipped, and no duplicate answers are written. If the run manifest pins the sample id, allow a sample whose ID set is a superset of the pinned one and record the new sample id in the manifest; refuse any other sample.
- [ ] Add the expansion step to `docs/runbook-main-run.md`. Commit and push. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

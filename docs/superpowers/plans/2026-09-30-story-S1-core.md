# S1: Story core (bootstrap, shares, funnel, domains, roles, method, CLI)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first: its Global Constraints and Data contract bind this lane.

Branch: feat/s1-story-core

**Goal:** `atlas story data` writes `story.json` with `meta`, `funnel`, `groups`, `cards` (base fields), `unplaced`, `domains`, `roles`, and `method`. It also provides the bootstrap engine and the IO helpers the other lanes reuse.

**Read first:**
- `AGENTS.md` and the master plan
- `src/atlas/sitedata/build.py`, `build_card_share.py`, `build_share.py` (the existing bootstrap pattern)
- `src/atlas/cards/engine/assign.py` (`read_answers`, `load_assignments`)
- `src/atlas/sitedata/build_quality.py` (`runs_rows`)
- `configs/run_phases.toml`

**Files you own:**
- `src/atlas/story/__init__.py`, `io.py`, `frame.py`, `boot.py`, `core.py`, `method.py`, `check.py`, `cli.py`
- `tests/story/test_io.py`, `test_boot.py`, `test_core.py`, `test_check.py`, `tests/story/world.py` (a synthetic world other lanes reuse)
- the AGENTS.md rows for `story data` and `story check`

## Task 1: Frame and IO

**Interfaces (produced):**
- `frame.load_frame(facet_sample, facets_run, assign_run, snapshot_id, cardset="main", version="t3") -> pandas.DataFrame`.
  - One row per phase-2 comment.
  - Columns: `comment_id, story_id, stratum, phase, wave, weight, period, author, account_type, domain, user_role, card, group, card_p, firsthand(bool), placed(bool)`, plus every facets@2 yes/no as `f_<qid>` (float `noul`) and `severity`, `specificity` scores.
  - `card` is set only when `card_p >= 0.5` and the card is not `none`.
- `io.merge_section(path, key, value) -> None`: an atomic read-modify-write of `story.json`.
- `io.est(values...) -> dict` builds an Est.

- [ ] **Test** `test_load_frame_columns_and_population` on `tests/story/world.py`:
  - a synthetic sample with pos and neg rows, facets answers, and assignments;
  - assert the columns;
  - `placed` implies `firsthand`;
  - a `neg` row keeps `phase == "neg"`.
- [ ] **Test** `test_merge_section_keeps_other_keys`: merging key B keeps key A byte-identical.
- [ ] Implement, pass, commit.

## Task 2: Joint bootstrap engine

**Interfaces (produced):**
- `boot.Replicates(frame_subset, R=1000, seed=0)`.
  - It aggregates rows to (stratum, story_id) pairs once.
  - It draws multinomial pair counts per stratum.
- `.totals(values: np.ndarray[n, k]) -> np.ndarray[R, k]`: weighted replicate sums.
- `.ratio(num_cols, den_col) -> (est, reps[R, k])`.
- `boot.summarize(est, reps, n) -> Est`: 25, 75, 2.5, 97.5 percentiles; `sparse = n < 30`.

- [ ] **Test** `test_ratio_matches_point_estimate`: the point estimate equals `sum(w*num)/sum(w*den)`.
- [ ] **Test** `test_same_seed_same_reps`: the same seed gives identical replicates.
- [ ] **Test** `test_single_thread_card_wide_interval`: a card whose rows all sit in one thread gets `hi95 - lo95` at least 5 times that of a spread card with the same n.
- [ ] Implement, pass, commit.

## Task 3: Shares, funnel, domains, roles, unplaced

**Interfaces (produced):** `core.build_core(frame, snapshot_id) -> dict` with keys `funnel, groups, cards, unplaced, domains, roles`, as in the contract.

**Definitions:**
- **Share denominator:** firsthand problems in screen_positive. Shares over all, H1, H2, quarters, and months come from joint replicates.
- **Change:**
  - `change.est = h2 - h1`, with the interval from the same replicates;
  - `p_adj` is the two-sided bootstrap p, BH-adjusted within groups and separately within cards;
  - `shrunk` is the empirical-Bayes shrunk change: normal-normal, prior mean 0, prior variance from the card changes by method of moments.
- **`domains`:**
  - `discussion` is the weighted domain share over ALL phase-2 rows, pos and neg together, which represents every screened comment;
  - `complaints` is the domain share over firsthand problems;
  - `rate = complaints / discussion`, from the same replicates.
- **`roles`:** role shares among problems with a stated role (not `unclear`/`other`), per group, plus `known_share`.
- **`funnel.steps`:**
  - `all` and `eligible` come from the snapshot manifest;
  - `screened` is 605,125 rows of `main-20260930b`;
  - `firsthand` and `placed` are weighted population estimates.
- **`funnel.months`:** comments per period from snapshot coverage, and `firsthand` as the weighted share per month.

- [ ] **Test** `test_shares_sum_leq_one`: per bucket, the group shares sum to at most 1.
- [ ] **Test** `test_sparse_period_flagged`: a period with 10 rows gets `sparse = true` and `n = 10`.
- [ ] **Test** `test_domains_use_neg_rows`: `discussion` changes when neg rows change; `complaints` does not.
- [ ] **Test** `test_change_same_replicates`: `change.est == h2.est - h1.est` within 1e-12.
- [ ] Implement in `core.py` (under 400 lines; split `core_domains.py` if needed). Pass, commit.

## Task 4: Method, meta, check, CLI

**Interfaces (produced):**
- `method.build_method(run_phases_toml, audit_run, benchmark_run, robust_screen_json, robust_assign_json) -> dict`. It reuses `runs_rows` and the eval JSON reader.
- `check.check_story(path) -> list[str]` returns problems. It flags:
  - any key named `text`, `body`, `author`, `username`, or `url`;
  - any string value not in the allowed vocabulary (card statements and short labels, group labels, domain and role names, tool names from `configs/tools.v1.yaml`, run IDs, period and quarter codes, the fixed title);
  - any `terms[*].term` whose `n_comments < 20` or `n_authors < 10`.
- **CLI:**
  - `story.cli.SECTIONS: dict[str, Callable[[args, story_path], None]]` is the registry that later lanes add to; `--with <name>` (repeatable) runs those builders after the core keys, and `--only-with` skips the core rebuild;
  - `atlas story data --out <path> [--facet-sample main-facets-20260930x] [--facets-run main-facets-20260930] [--assign-run main-cards-final2-t3] [--audit-run pilot-20260929-cards] [--benchmark-run main-benchmark-20260930] [--robust-screen runs/robust-screen-compare.json] [--robust-assign runs/robust-assign-compare.json] [--run-phases configs/run_phases.toml]` writes S1's keys through `merge_section`;
  - `atlas story check <path>` prints `story: ok` or the problems and exits 1.

- [ ] **Test** `test_check_flags_unknown_string`: an injected free-text string fails the check.
- [ ] **Test** `test_with_runs_registered_section`: a dummy SECTIONS entry is called once with the story path.
- [ ] **Test** `test_cli_writes_core_keys` on the synthetic world: all S1 keys present, and `story check` passes.
- [ ] Implement, add the AGENTS.md rows, pass, commit. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

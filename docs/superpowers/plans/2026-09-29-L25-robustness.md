# L25: Paraphrase robustness for the screen and the card assignment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l25-robustness

**Goal:** Show that the headline numbers do not hinge on the exact question wording. Re-ask Jev with two paraphrased wordings on a random subsample, then compare against the main run. The design doc (section 6) budgets $1.30 under `robustness`. This lane builds the commands; only the main session runs them with `--yes`.

**Read first:**
- `AGENTS.md`
- `src/atlas/screen/` (the packed screen, `screen run --question-set` is not a flag yet)
- `src/atlas/cards/engine/assign.py`, `cli.py`
- `src/atlas/sitedata/build_share.py` (`boot_ratio`)
- `configs/questions/screen.v1.json`
- `docs/superpowers/specs/2026-09-29-analysis-design.md`

**Files you own:**
- `src/atlas/robustness/__init__.py`, `src/atlas/robustness/cli.py`, `src/atlas/robustness/subsample.py`, `src/atlas/robustness/compare.py` (the main session registers `atlas.robustness.cli` and creates `tests/robustness/__init__.py`)
- `configs/questions/screen_para1.v1.json`, `configs/questions/screen_para2.v1.json`
- `configs/cards/paraphrases.v1.json`
- `src/atlas/screen/cli.py` (only a new `--question-set` option, default `screen@1`)
- `src/atlas/cards/engine/assign.py` (only optional `group_instructions` and `card_instructions` keyword arguments on `assign`, defaulting to the current constants)
- `tests/robustness/test_*.py`, and test additions for the two small options above
- AGENTS.md command-table rows for the new commands (allowed)

### Task 25.1: Paraphrased question sets
- [ ] Write `screen_para1` and `screen_para2`: the same question IDs, types, and criteria keys as `screen.v1.json`, with reworded `instructions` and reworded criteria descriptions, each keeping the meaning.
- [ ] Write `configs/cards/paraphrases.v1.json`: two reworded pairs `{group_instructions, card_instructions}`.
- [ ] **Test** that the paraphrase sets load, keep the question IDs, types, and criteria keys of the original, and differ in wording.
- [ ] Add `screen run --question-set <name@version>` (default `screen@1`) and the `assign` keyword arguments, each with a test that the default path is unchanged. Commit and push.

### Task 25.2: Subsamples
- [ ] `robust subsample-screen --sample main-20260930b --n 20000 --seed 20261002 --sample-id robust-screen-20261002`: stratified SRSWOR within the sample's `stratum`, proportional to stratum size.
  - The output has the same schema as the parent sample, and each `weight` is multiplied by (parent rows in the stratum) / (subsample rows in the stratum), so the weights still sum to the population.
  - Manifest JSON alongside, like other samples.
- [ ] `robust subsample-items --items <parquet> --n 3000 --seed 20261003 --out <parquet>`: simple random, sorted by `comment_id`.
- [ ] **Test** determinism, schema, and that weights sum to the parent total within 1e-6 relative. Commit and push.

### Task 25.3: Paraphrase runs
- [ ] `robust assign-paraphrase --cardset --version --items <sub> --run <id> --para 1|2 [--rpm 1000] [--yes]` runs `assign` with the paraphrase instructions under budget `robustness`. It prints an estimate first.
- [ ] Screen paraphrases use `screen run --sample robust-screen-20261002 --question-set screen_para1@1 --run ... --budget robustness`, so no new command is needed.
- [ ] **Test** with the mock transport. Commit and push.

### Task 25.4: Comparisons
- [ ] `robust compare-screen --main-run main-screen-20260930 --runs <para1>,<para2> --sample robust-screen-20261002 --cutoff 0.7 --out <json>`: for the main answers restricted to the subsample and each paraphrase run, report:
  - weighted prevalence at the cutoff, with a stratified thread-bootstrap interval (`boot_ratio`);
  - item-level agreement with main (share of items on the same side of the cutoff) and Cohen's kappa;
  - Spearman correlation of `firsthand_p`.
- [ ] `robust compare-assign --main-run main-cards-20260930 --runs <p1>,<p2> --version t2 --out <json>`: group agreement, card agreement (both counting `none`), and the top-20 card shares under each run with the max absolute difference.
- [ ] Outputs hold IDs and numbers only, never text. **Test** each with synthetic runs where the expected numbers are computed by hand. Commit and push.

- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

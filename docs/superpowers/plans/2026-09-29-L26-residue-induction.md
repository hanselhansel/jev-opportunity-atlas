# L26: Residue reassignment after an induction round

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l26-residue-induction

**Goal:** After an induction round adds cards to a cardset (t3 = t2 plus new cards, same groups and group labels), reassign only the residue at the card level, then write one combined assignment table. The residue is items whose base assignment has a real group but card `none` or `card_p < 0.5`. The group answer is already known from the base run, so re-asking it wastes money (the cache key includes the question-set label, so it would not hit).

**Read first:**
- `AGENTS.md`
- `src/atlas/cards/engine/assign.py` (`card_item`, `engine_qs`, `read_answers`, `write_assignments`, `load_assignments`, `AssignResult`, and how a row is built from group and card answers)
- `src/atlas/cards/engine/cli.py`, `src/atlas/cards/engine/cardset.py`
- `src/atlas/inference/runner.py`

**Files you own:**
- `src/atlas/cards/engine/induce.py` (new)
- `src/atlas/cards/engine/cli.py` (register one subcommand)
- `tests/cards/engine/test_induce.py`
- the AGENTS.md command-table row (allowed)

### Task 26.1: `cards induce`
- [ ] **Test** with the mock transport, a synthetic base cardset `t2`, and a superset `t3` (same groups and labels; every t2 card unchanged; extra cards added):
  - `check_superset(base_cs, new_cs)` raises unless groups, group labels, and every base card's statement and group are identical.
  - `residue(base_rows)`: rows whose `group_id` is a real group and whose `card_id` is null, `none`, or has `card_p < 0.5`.
  - For residue rows only, the command runs card-level calls with `card_item(comment_id, pain_sentence, sentences, new_cs, base_group_id)` under question set label `assign-c@<new version>`, budget `assign`, with `--rpm` (default 1000) and `--concurrency` (default 8).
  - No group-level call is made (assert on the mock).
  - The combined table in `<new run>/assignments-<new version>.parquet` (same schema, `taxonomy_version` = new version) holds:
    - every non-residue base row unchanged except `run_id` and `taxonomy_version`;
    - every residue row rebuilt from the base group answer plus the new card answer, the same way `assign` builds rows (card_p, card_confidence, top-2 metadata);
    - group-none rows copied unchanged.
  - A sidecar `<new run>/induce-<new version>.json` records base run, base version, counts of carried, reassigned, and moved-to-a-card rows, and the new cards' assigned counts.
  - A rerun resumes without duplicate paid calls.
- [ ] **CLI:** `cards induce --base-run <run> --base-version t2 --cardset main --version t3 --run <new run> --items <items parquet> [--rpm] [--concurrency] [--yes]`. It prints an estimate first and dispatches only with `--yes`. It also copies `pain.parquet` from the base run so downstream commands work on the new run.
- [ ] Commit and push. `scripts/verify.sh` prints `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

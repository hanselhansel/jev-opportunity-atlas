# L16: Labeler modes for audits (facets, card assignments, merges, interview-worthiness)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Branch: feat/l16-labeler-modes

**Goal:** Hansel can blind-label every kind of item the analysis design needs audited, in the same Streamlit labeler. The audits and their sizes (design section 7):
- deep-facet audit (150)
- card-assignment audit (200; 100 of them for the pilot go/no-go)
- merge audit (50)
- top-card "worth interviewing" review (200)

Labels feed the same append-only store and the gold-draw records used by PPI.

**Architecture:**
- Extend `src/atlas/evaluation/labeler_app.py` with a mode chosen by the queue file's `label_set`.
- Each mode is a small module in `src/atlas/evaluation/modes/` that defines what to show and which questions to ask.
- Extend `atlas.evaluation.store.LabelStore` validation with each mode's allowed values.
- `atlas label run --label-set` gains the new sets.
- Queue builders for the new sets live in `src/atlas/evaluation/audit_queues.py`. They draw with known probabilities and write `GOLD_DRAWS` rows through the same writer L7 uses (`atlas.pilot.gold`).

Blindness rules:
- **Facet audit:** shows the comment and parent only, never Jev's facet answers.
- **Card-assignment audit:** necessarily shows the pain sentence and one candidate card. Half of the shown cards are Jev's assignment and half are a random other card from the same group (recorded in the queue, hidden from the UI), so Hansel judges "does this card describe this problem?" without knowing which is Jev's.
- **Merge audit:** shows two card statements.
- **Worth-interviewing review:** shows a card with 5 sampled example pain sentences and its metrics (authors, threads, periods, domains). It is a judgment, not a blind check, and it is labeled as such.

**Read first:** `AGENTS.md`, `configs/rubric.v1.md`, `src/atlas/evaluation/labeler_app.py`, `store.py`, `queue.py`, `cli.py`, `src/atlas/pilot/gold.py`, `src/atlas/contracts.py` (`LABELS`, `GOLD_DRAWS`, `ASSIGNMENTS`, `CARDS`), `src/atlas/cards/engine/cardset.py`, `docs/superpowers/specs/2026-09-29-analysis-design.md` section 7.

**Files you own:**
- `src/atlas/evaluation/labeler_app.py`, `store.py`, `cli.py`, `audit_queues.py` (new), `modes/__init__.py`, `modes/facets.py`, `modes/assignment.py`, `modes/merge.py`, `modes/interview.py`
- `configs/rubric.v1.md`: append a section per new mode, in the same style; do not change existing sections
- `tests/evaluation/test_modes_*.py`, `tests/evaluation/test_audit_queues.py`

### Task 16.1: Store validation per mode
- [ ] **Step 1: Test** allowed values:
  - `facet_audit`: `workaround`, `paid`, `switched`, `abandoned`, `cost_time`, `cost_money` take yes, no, unsure; `resolution` takes resolved, unresolved, unclear.
  - `assignment_audit`: `fits` takes yes, partly, no, unsure.
  - `merge_audit`: `same` takes same, related, different.
  - `interview`: `worth_interviewing` takes strong, maybe, no, plus an optional free-text `why`, at most 280 characters.

  Unknown values raise.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 16.2: Audit queue builders with known probabilities
- [ ] **Step 1: Test**
  - `facet_audit_queue(run_id, n=150, seed)` stratifies by the comment's max facet probability, in bands [0.5, 1] and [0, 0.5), 75 each.
  - `assignment_audit_queue(assign_run_id, taxonomy_version, n=200, seed)` stratifies by `card_confidence` band, at 0.5, and assigns the shown card: Jev's card with probability 0.5, otherwise a random other card in the same group, with the seed recorded.
  - `merge_audit_queue(scored_pairs, n=50, seed)` stratifies by expected score band.
  - `interview_queue(card_metrics, top_k=200)` is not a probability draw; purpose `audit`, `selection_prob` null. The `GOLD_DRAWS` writer must allow null only for this purpose. Every builder writes `GOLD_DRAWS` rows.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass. Step 5: Commit and push.**

### Task 16.3: Mode UIs
- [ ] **Step 1: Test** (AST and static checks like the existing blind test): the facet mode never reads `answers` for facet questions. The assignment mode never reveals which card is Jev's: no string such as "Jev" or "assigned" is rendered. Each mode module has `render(item)` and `questions()`.
- [ ] **Step 2: Implement** the modes in `modes/`. Add a visible "Comment" heading above the comment text in every mode, including the existing calibration mode, so the comment is never confused with the parent. Keep a progress bar, back and save, resume, 10% hidden repeats for the facet and assignment audits, and timing capture.
- [ ] **Step 3:** Render-check each mode locally with a synthetic snapshot (headless Chrome screenshot as in L6's continuation). **Step 4: Commit and push.**

### Task 16.4: CLI and evaluation
- [ ] `atlas label run --label-set facet_audit|assignment_audit|merge_audit|interview ...` builds or reuses the queue and launches.
- [ ] `atlas eval run --label-set assignment_audit --run <assign_run>` reports:
  - precision of Jev's assigned card: share of `fits` in {yes, partly} for Jev-shown items, and {yes} alone
  - the same for random-card items, as a baseline that must be much lower
  - interval by bootstrap
  - agreement on repeats
- [ ] The same for `facet_audit`: per-facet precision and recall at 0.5, weighted by band rates.
- [ ] `scripts/verify.sh` must print `verify: ok`. Open the PR per AGENTS.md. Final message: PR URL and pytest summary line.

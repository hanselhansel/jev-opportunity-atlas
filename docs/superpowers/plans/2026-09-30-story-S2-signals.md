# S2: Per-card signals, breadth, concentration, specification ranks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first.

Branch: feat/s2-story-signals

**Goal:** Add `cards[].coping`, `costs`, `quality`, `breadth`, `concentration`, and the top-level `spec_ranks` to `story.json`.

**Read first:** the master plan, `src/atlas/story/frame.py`, `boot.py`, `core.py`, `io.py` (from S1), `src/atlas/robustness/compare.py`.

**Files you own:** `src/atlas/story/signals.py`, `breadth.py`, `concentration.py`, `spec_ranks.py`; `tests/story/test_signals.py`, `test_breadth.py`, `test_concentration.py`, `test_spec_ranks.py`; one `--with signals` step in `story/cli.py`.

**Interfaces:**
- **Consumes:** `frame.load_frame`, `boot.Replicates`, `boot.summarize`, `io.merge_section`.
- **Produces:**
  - `signals.card_signals(frame) -> {card: {coping, costs, quality}}`;
  - `breadth.card_breadth(frame) -> {card: breadth}`;
  - `concentration.card_concentration(frame, sims=500, seed=0) -> {card: concentration}`;
  - `spec_ranks.spec_ranks(frame, para_runs) -> list`.

## Task 1: Coping, costs, quality
**Definitions:**
- **Coping:**
  - `paid`, `switched`, `abandoned`, and `workaround` are weighted shares of the card's problems with `f_<q> >= 0.5`;
  - `commercial` is the share with any of paid, switched, or abandoned.
- **Costs:** `money = f_cost_money`, `time = f_cost_time`, `reliability = f_cost_reliability`, `customers = f_cost_customers`.
- **Quality:** `severe3` = share with `severity >= 2.5`; `specific3` = share with `specificity >= 2.5`.
- **Cards under 30 problems:** every Est has `sparse = true`.

- [ ] **Test** `test_commercial_is_any_not_sum`: one problem that paid and switched counts once.
- [ ] **Test** `test_thin_card_sparse`: a card with 12 problems gets `sparse = true` on every Est.
- [ ] Implement, pass, commit.

## Task 2: Breadth
**Definitions:**
- **`domains`:** the card's weighted domain distribution.
- **`entropy`:**
  - Chao-Shen coverage-adjusted Shannon entropy in bits, using counts;
  - the interval comes from bootstrap replicates of the card's rows;
  - `sparse` when fewer than 100 problems.
- **`residuals`:** standardized residuals of the card × domain table against independence. Pearson residual = (obs - exp) / sqrt(exp) on unweighted counts.

- [ ] **Test** `test_entropy_single_domain_zero`: a card in one domain has entropy 0.
- [ ] **Test** `test_entropy_uniform_max`: a card spread evenly over 4 domains has entropy near 2 bits (within 0.1 at n = 4000).
- [ ] Implement, pass, commit.

## Task 3: Concentration
**Definitions:**
- **`top3_threads`:** the weighted share of the card's problems from its 3 largest threads.
- **`top3_authors`:** the same for authors.
- **Null bands:**
  - simulate `sims` replicates that reassign the card's n problems to threads with probability proportional to each thread's total firsthand problem count;
  - do the same for authors;
  - the band is the 2.5 and 97.5 percentiles of the simulated top-3 share.
- **`flagged`:** true when either observed value exceeds its band's upper bound.

- [ ] **Test** `test_one_thread_card_flagged`: 80% of a card's problems in one thread gives `flagged = true`.
- [ ] **Test** `test_spread_card_not_flagged`.
- [ ] Implement, pass, commit.

## Task 4: Specification ranks
**Definitions:**
- `main_rank` is the rank by full-year share.
- **Alternatives:**
  - `card_p_0.7` counts a card only when `card_p >= 0.7`;
  - `one_per_thread` keeps one problem per (card, thread), weight = max;
  - `one_per_author` does the same per (card, author);
  - `para1` and `para2` use unweighted card counts in `runs/robust-assign-para{1,2}/assignments-t3.parquet` within the 3,000-item subsample.
- **Rows:** the union of every alternative's top 20.

- [ ] **Test** `test_spec_ranks_union_top20`: a card that is top 20 only under `one_per_author` appears.
- [ ] Implement, wire `story data --with signals`, pass, commit. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

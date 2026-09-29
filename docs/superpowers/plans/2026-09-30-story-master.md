# Story essay implementation plan (master)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement your lane plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This master file holds the shared constraints and the data contract every lane must follow.

**Goal:** Build the data, the three small Jev runs, and an interactive draft essay for "Startup opportunities identified via Hacker News conversations between 2025-26".

**Architecture:**
- Python lanes compute one aggregate `story.json` from saved runs, with no HN text.
- Three new commands run small Jev steps: named fixes, Show HN builders, and replies on more cards.
- A static front-end in `essay/` renders about 25 interactive charts from `story.json`. The main session writes the prose and publishes the draft as a private artifact.

**Tech stack:** Python 3.11 (numpy, scipy, pandas, duckdb, scikit-learn, pyarrow; no new dependencies). Front-end: plain ES modules with D3 v7, Observable Plot 0.6, d3-voronoi-treemap, and Scrollama, all from cdn.jsdelivr.net.

**Spec:** `docs/superpowers/specs/2026-09-30-story-design.md`. **Visual research:** the per-chart designs in `docs/superpowers/specs/2026-09-30-story-visuals.md`.

## Global Constraints

- **No HN text or usernames** in tracked files, `story.json`, fixtures, or the essay.
  - The only words allowed are:
    - card and group statements and short labels;
    - domain and role names;
    - tool names from `configs/tools.v1.yaml`;
    - terms that passed the S4 gate (at least 20 comments and at least 10 distinct authors, plus the denylist).
- **Population:**
  - phase-2 rows of `data/samples/main-facets-20260930x.parquet`;
  - `phase == "pos"` (screen_positive);
  - facets@2 `account_type == "firsthand_account"`.
- **Weight:** `weight` (w1/p2) from that sample. Never the screen weight.
- **Assignments:**
  - run `main-cards-final2-t3`, taxonomy `t3`, cardset `main`;
  - a card counts when `card_p >= 0.5` and the card is not `none`;
  - short labels come from `configs/cards/main.t3.labels.yaml`.
- **Facets:**
  - run `main-facets-20260930`, question set `facets@2`;
  - a yes/no facet counts as yes when `noul >= 0.5`;
  - severity and specificity are `score` values on a 0 to 3 scale.
- **Intervals:**
  - a stratified thread bootstrap: strata = phase-2 `stratum`, clusters = `story_id`, R = 1000, seed 0;
  - every estimate uses the Estimate object defined below;
  - differences and ranks come from the same joint replicates.
- **Periods:** P01 to P12. H1 = P01 to P06, H2 = P07 to P12. Q1 = P01 to P03, and so on.
- **Copy:** every UI sentence and bullet is at most 15 words. No em dashes. No banned words (see CLAUDE.md).
- **Front-end:**
  - scripts come only from cdn.jsdelivr.net or cdnjs.cloudflare.com;
  - it works at 375 px wide with no horizontal scroll;
  - it honors reduced motion.
- **Repo rules:**
  - source files under 400 lines;
  - no edits to frozen files;
  - Jev calls only in the main session with `--yes`;
  - tests use the mock transport.

## Review Focus

1. **Thin cards** (under 30 problems, or 0 sampled launches) must show "too few", never a tight interval. The test goes in S2 and S3.
2. **Cards outside the replies top 40** have `unsolved = null`. The score must drop that component for them and say so, not treat it as 0. The test goes in S3.
3. **A username, URL, or email** that clears k-anonymity (a popular handle) must never reach `terms`. The test goes in S4.
4. **A period with few rows** still gets a share, with `n` and a `sparse` flag at n under 30. The test goes in S1.
5. **All opportunity weights set to 0** must fall back to equal weights, with a notice. The test goes in S7.

## Data contract: `story.json` (schema `story.v1`)

**Estimate object** (`Est`): `{"est": float, "lo50": float, "hi50": float, "lo95": float, "hi95": float, "n": int, "sparse": bool}`. It is null when not computable.

**Top-level keys and the lane that fills each:**

| Key | Shape | Lane |
|---|---|---|
| `meta` | `{schema:"story.v1", title, window_start, window_end, built_at, code_commit, runs:{screen,facets,assign,replies,solutions,builders}, taxonomy:"t3"}` | S1 |
| `funnel` | `{steps:[{key,label,count}], months:[{period, comments:int, firsthand:Est}]}` with steps `all, eligible, screened, firsthand, placed` | S1 |
| `groups` | `[{id, label, short, share:Est, h1:Est, h2:Est, change:{est,lo95,hi95,p_adj}, quarters:{Q1..Q4:Est}, months:{P01..P12:Est}, cards:[ids], top_thread_share:float}]` | S1 |
| `cards` | `[{id, group, short, statement, share:Est, h1:Est, h2:Est, change:{est,lo95,hi95,p_adj,shrunk}, quarters:{..}, n_problems, n_authors, n_threads}]`; S2, S3, S5, S6 add fields below | S1 |
| `unplaced` | `{share:Est, domains:{name:Est}, roles:{name:Est}}` | S1 |
| `domains` | `[{id, discussion:Est, complaints:Est, rate:Est}]` (rate = complaints over discussion) | S1 |
| `roles` | `{by_group:{gid:{role:Est}}, known_share:{gid:Est}}` | S1 |
| `cards[].coping` | `{paid, switched, abandoned, workaround, commercial}` each an Est; commercial = max of paid, switched, abandoned per problem | S2 |
| `cards[].costs` | `{money, time, reliability, customers}` Est | S2 |
| `cards[].quality` | `{severe3:Est, specific3:Est}` | S2 |
| `cards[].breadth` | `{entropy:Est, domains:{name:float}, residuals:{name:float}}` | S2 |
| `cards[].concentration` | `{top3_threads:float, top3_authors:float, null_threads:[lo,hi], null_authors:[lo,hi], flagged:bool}` | S2 |
| `spec_ranks` | `[{card, main_rank, alt_ranks:{alt_key:int}}]` with alts `card_p_0.7, one_per_thread, one_per_author, para1, para2` | S2 |
| `cards[].unsolved` | `{unsolved:Est, author_solved:Est}` or null | S3 |
| `cards[].score` | `{components:{name:float in [0,1] or null}, rank_quantiles:[int x 20]}` | S3 |
| `score_presets` | `{balanced:{...}, growth:{...}, paid_pain:{...}, underbuilt:{...}}` weights per component | S3 |
| `bundles` | `[{id, cards:[ids], share:Est, groups_spanned:int, persistence:float}]` | S3 |
| `edges` | `[{a, b, score}]`, the top 8 neighbors per card by merge score | S3 |
| `terms` | `{gid:[{term, z, lo95, hi95, n_comments, n_authors}]}` | S4 |
| `tools` | `[{name, category, threads, fix_threads, complaint_threads, fix_share:Est}]`, and `cards[].tools:{fixes:[{name,threads}], blamed:[{name,threads}]}` | S5 |
| `builders` | `{n_sampled, n_population, match_rate:Est}`, and `cards[].builders:{launch_share:Est, ratio:Est}` | S6 |
| `method` | `{runs:[{phase, calls, usd, p50_ms, wall_s}], total_usd, total_calls, quality:{audit_jev, audit_random, benchmark_acc, planted_recovery}, wording:{screen:[{run, prevalence:Est}], assign:{card_agreement:[float], group_agreement:[float]}}}` | S1 |

Each lane writes its keys through `atlas.story.io.merge_section(path, key, value)` (S1). A lane never overwrites another lane's keys.

## Lanes and order

| Lane | Plan | Owner | Starts after |
|---|---|---|---|
| S1 core shares, funnel, domains, roles, method, io, bootstrap, CLI | `2026-09-30-story-S1-core.md` | Devin | this master merges |
| S2 per-card signals, breadth, concentration, spec ranks | `2026-09-30-story-S2-signals.md` | Devin | S1 merged |
| S3 score, rank stability, bundles, edges, replies join | `2026-09-30-story-S3-score.md` | Devin | S1 merged |
| S4 distinctive terms | `2026-09-30-story-S4-terms.md` | Devin | S1 merged |
| S5 named fixes (dictionary match plus Jev confirm) | `2026-09-30-story-S5-tools.md` | Devin | this master merges |
| S6 Show HN builders (sample plus assign) | `2026-09-30-story-S6-builders.md` | Devin | this master merges |
| S7 essay front-end from a fixture `story.json` | `2026-09-30-story-S7-frontend.md` | Devin | this master merges |

S1, S5, S6, and S7 run in parallel. S2, S3, and S4 run in parallel after S1.

## Main-session tasks (Claude)

### Task M1: Budgets, tools dictionary, registry
- [ ] Update `configs/budgets.toml`:
  - `discovery = 0.00`, `robustness = 0.95`, `replies = 0.65`;
  - add `solutions = 0.30` and `builders = 0.70`;
  - fix any test that hard-codes these caps.
- [ ] Write `configs/tools.v1.yaml`: about 300 products and companies as `{name, aliases:[...], category}`.
  - Categories: `ai_model`, `ai_coding`, `dev_tool`, `cloud_infra`, `os_device`, `consumer_app`, `saas_business`, `other`.
- [ ] Register `atlas.story.cli`, `atlas.solutions.cli`, and `atlas.builders.cli` in `src/atlas/cli.py`.
- [ ] Create `tests/story/__init__.py`, `tests/solutions/__init__.py`, and `tests/builders/__init__.py`.
- [ ] Add `essay/data/` to `.gitignore`. Copy the visual research to `docs/superpowers/specs/2026-09-30-story-visuals.md`.
- [ ] Commit, PR, merge.

### Task M2: Paid runs (after S5 and S6 merge)
- [ ] `cards replies --run main-cards-final2-t3 --version t3 --snapshot hn-2025-09-28_2026-09-28-v1 --top-cards 40 --yes`. Check the ledger stays under the `replies` cap.
- [ ] `solutions run --yes`, then `builders draw` and `builders run --yes`. Record each cost against its estimate.

### Task M3: Build, write, review, publish
- [ ] Run `atlas story data --out essay/data/story.json`, then `atlas story check essay/data/story.json`. It must print `story: ok`.
- [ ] Write `essay/content/story.md`:
  - chapter prose from the real numbers;
  - every sentence at most 15 words;
  - each chapter ends with a "for a builder" line.
- [ ] Render at 1280 px and 375 px, check every chart against the numbers, and fix or file lane bugs.
- [ ] Publish `essay/` as a private artifact. Send Hansel the link and the review questions.
- [ ] After Hansel's review, draft the X trailer (8 to 10 posts, one chart each) in Hansel's voice. Add matching static specs to `xspecs.py` through a follow-up lane.

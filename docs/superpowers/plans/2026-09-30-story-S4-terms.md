# S4: Distinctive terms per group (aggregate words only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` first. This lane reads HN text locally. Only aggregate terms that pass the gate may leave the function.

Branch: feat/s4-story-terms

**Goal:** Add `terms` to `story.json`: for each group, the 8 most distinctive words or two-word phrases in its problems' pain sentences, with intervals.

**Read first:** the master plan; S1's `frame.py` and `io.py`; `runs/main-cards-final2-t3/pain.parquet` (columns `comment_id, pain_sentence`); `src/atlas/sources/htmltext.py`.

**Files you own:** `src/atlas/story/terms.py`, `configs/terms_denylist.txt`, `tests/story/test_terms.py`, a `--with terms` step in `story/cli.py`.

**Interfaces:**
- **Consumes:** the frame (`comment_id, group, author, placed`) and `pain.parquet`.
- **Produces:** `terms.group_terms(frame, pain: dict[int,str], k_comments=20, k_authors=10, top=8) -> dict[gid, list]`.

## Task 1: Tokenize and gate
**Tokenizing:**
- Lowercase, keep `[a-z][a-z0-9+#.-]*` tokens of 3 to 30 characters.
- Drop English stopwords using the sklearn list.
- Form unigrams and bigrams (bigrams of two non-stopword tokens).

**Gate (all must pass):**
- the term appears in at least 20 distinct comments and from at least 10 distinct authors;
- it contains no digit run of 4 or more;
- it matches no URL, email, or `@handle` pattern;
- it is not in `configs/terms_denylist.txt`;
- it is not equal to any author name in the frame (case-insensitive).

The denylist seeds: profanity, slurs, and common first names.

- [ ] **Test** `test_username_never_passes`: an author name used by 30 other authors in 40 comments is dropped.
- [ ] **Test** `test_url_and_email_dropped`.
- [ ] **Test** `test_rare_term_dropped`: 19 comments fails; 20 comments and 10 authors passes.
- [ ] Implement, pass, commit.

## Task 2: Log-odds with informative Dirichlet prior
- Use Monroe, Colaresi and Quinn (2008).
- Each group is compared with all other placed problems. The prior is the corpus-wide term counts, scaled so the prior total is 500.
- `z` is the z-score of the log-odds difference, with 95% interval `z ± 1.96`, on the delta scale. Store `lo95` and `hi95` as the log-odds interval.
- Keep only terms with BH-adjusted q < 0.05 across all term × group tests, then take the top 8 by z per group.

- [ ] **Test** `test_planted_term_ranks_first`: a term injected only into group g01 comments ranks first for g01.
- [ ] **Test** `test_output_has_no_raw_sentence`: no output string contains a space-separated run longer than 2 tokens.
- [ ] Implement, wire `story data --with terms`, pass, commit. `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

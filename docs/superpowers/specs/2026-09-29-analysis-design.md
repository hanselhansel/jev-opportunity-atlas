# Analysis design: first principles, Jev-first, $25

Status: draft for Hansel's approval, 2026-09-29. Extends the approved spec; replaces its
sections 4 (sizing), 6 (topics and findings), and the analysis parts of 7 and 8.

## 1. The actual problem

Pick the 3 problem spaces worth 20 customer interviews next quarter, and publish on X
only what survives an honest test, with Jev doing the analysis, all for at most $25 of
Jev credit and about 8 hours of Hansel's labeling.

The decision comes first. Every chart must change which problems get interviewed or
what a reader believes. Anything else is cut.

## 2. Hard truths

- **Money.** $25 of credit at $0.042 per million input tokens is about 595M input tokens,
  total, including retries and mistakes. Output tokens are free.
- **What drives cost.** Question text is paid on every call. A one-sentence comment with
  two questions cost 366 tokens. Many questions in one call share one read of the comment.
- **Scale.** About 3.8M eligible comments. A full census costs $40 to $220 depending on
  the question set, so a census is impossible. Sampling is forced.
- **What Jev can do.** Yes/no probabilities, choice over up to 255 options with
  confidence, ordinal scores, and very consistent answers (TypeSafe measured a
  per-question standard deviation of 0.01 across repeats). It reads literally and
  struggles with negation, counting, and dates.
- **What Jev cannot do.** Write text or produce embeddings. So problem names and
  descriptions need a writer (Claude, reviewed by Hansel, disclosed).
- **Human time.** About 1,000 labels (6 to 8 hours).
- **Rate.** 1,200 requests per minute. 300k calls take about 4 to 5 hours.
- **The data.** HN commenters are a self-selected, developer-heavy, vocal minority: in a
  forum, about 1% of people write most of the posts. Comments have no location. A few
  threads can dominate any count.

## 3. Assumptions we are dropping

| Assumption | From | Why it goes |
|---|---|---|
| Organize by topic, then find problems inside a topic | Handoff's "onion" | The unit of value is the problem. Topic is one facet of it. Convergence across topics is a key signal, and a topic tree hides it |
| Screen every comment | My earlier proposal | Unaffordable, and unnecessary: a good sample plus bias correction gives valid numbers |
| Rank problems by how often they are mentioned | Common practice | Research finds frequency only weakly related to need importance. Rank on distinct authors, spread, workarounds, spend, switching, and unsolvedness |
| Model labels are the measurement | Common practice | Uncorrected model labels at 80 to 90% accuracy can drop real interval coverage to about 40%. Use prediction-powered inference with human gold labels |
| Monthly trend charts | Handoff | About 1,000 gold labels cannot support 12 months by segment. Use half-year and quarter comparisons with intervals |
| Keyword clusters (BERTopic style) | Common practice | Bag-of-words topics do not describe needs |
| Regional analysis by commenter | Hansel's question | No location data exists. Only "comments that name a country or legal regime" is honest |

## 4. The pipeline (built from the truths)

Each step says who does it. Jev does everything except write card text and make
decisions.

**Step 0. Sample (code, free).** Stratify eligible comments by period, thread type,
engagement, comment length, and a free "pain-word" flag (for example "we spent",
"broke", "workaround", "switched", "paying"). Oversample the high-yield groups, with
every comment keeping a known selection probability. No group gets zero, so
keyword-free complaints are still found and counted. Expected yield: 3 to 5 times more
firsthand problems per dollar than a flat sample. Split the sample by thread into an
**explore half** and a **confirm half** before any analysis.

**Step 1. Screen (Jev).** About 300k sampled comments. Two short questions: firsthand
problem (yes/no) and account type (choice). State is the comment plus 600 characters of
parent.

**Step 2. Facets (Jev).** About 25k firsthand problems. In one call per comment:

- pain sentence (choice over sentence IDs)
- domain (choice)
- actor role (choice)
- named jurisdiction (choice, including "none")
- timing, workaround, 5 consequence types, paid, switched, tried alternatives,
  abandoned, resolved (yes/no each)
- severity and specificity (scores)

**Step 3. Need cards (Claude writes, Hansel approves).** From a stratified sample of
pain sentences in the explore half, Claude drafts solution-independent need statements,
following the customer-need rules in Timoshenko, Mao and Hauser (2025): not an opinion,
not a solution, not too generic, not too specific. Hansel edits and approves. Target is
about 150 to 300 cards in about 30 groups.

**Step 4. Assign (Jev).** Two-level choice per problem comment: first the group, then
the card within it, each with "none of these". Same pattern as TnT-LLM, TopicGPT, and
TypeSafe's hierarchical-classification recipe. Low confidence backs off to the group.

**Step 5. Induce on the residue (Claude drafts, Jev reassigns).** Sample the "none of
these" pile, draft new cards, reassign. Stop when the residue share levels off (2 to 3
rounds).

**Step 6. Merge (Jev).** A 3-level score, "same problem, related, or different", for
card pairs within a group and for flagged pairs across groups. This is TypeSafe's
entity-alignment recipe.

**Step 7. Verify (Jev plus Hansel).** A yes/no membership check per assignment, and a
planted-needs test: 50 synthetic comments with 5 known needs mixed in must land on the
right cards (the method Clio used to validate its clustering).

**Step 8. Unsolvedness (Jev plus free HN data).** For comments on the top cards, fetch
direct replies (free) and ask "Does this reply name an existing tool that solves the
problem?" This separates met needs from unmet ones.

**Step 9. Estimate (code, with Hansel's gold labels).** Prediction-powered inference
(PPI++, `ppi_py`) for every published proportion, using a gold sample drawn with known
probabilities (stratified by period, segment, and Jev confidence, plus a 30% uniform
slice).
- Ratios such as "share of firsthand problems about X" are estimated as two corrected
  quantities, never by conditioning on Jev's predicted label.
- Thread-weighted and author-capped versions are the published ones.
- Leave-one-thread-out and top-1%-thread-drop checks run on every headline.
- Benjamini-Hochberg correction applies across the many comparisons.
- DSL is used as a cross-check where a regression is reported.

**Step 10. Rank (code, Hansel decides).** Card score from visible factors, weights shown:
- distinct authors (capped)
- distinct threads and periods
- distinct domains and roles (convergence)
- workaround rate and paid, switched, or abandoned rate
- stated cost
- unsolved share
- trend (half-year, with interval)

The autoresearch loop from TypeSafe's cookbook then proposes extra yes/no features, Jev
answers them, and a small model learns which features predict Hansel's "worth
interviewing" labels on 200 cards. The top cards are confirmed on the confirm half
before anything is published.

## 5. The cuts Hansel asked about

- **Convergence across topics.** Distinct domains and roles per card, shown as a problem
  × domain matrix. This is first-class, not an afterthought.
- **Time.** Half-year and quarter share of each card, with intervals. A change is only
  claimed when it survives dropping the top thread and a pre-set test. Any month where
  one thread supplies over 10% of matches is flagged.
- **Regions.** Cards by "named jurisdiction", reported only as "comments that mention
  the EU/US/India…".
- **Also.** Role (buyer versus user), thread type (Ask HN versus Show HN), and
  commercial signal (paid, switched, abandoned).

## 6. Budget ($25 of credit, hard cap)

| Phase | Estimate | Cap |
|---|---|---|
| Pilot (2,000 comments; measures real tokens per question) | $0.40 | $0.50 |
| Screen (~300k) | $5.70 | $6.50 |
| Facets (~25k) | $2.10 | $2.50 |
| Assign + residue rounds | $2.10 | $2.50 |
| Merge + verify | $0.40 | $0.60 |
| Reply unsolvedness check | $0.20 | $0.30 |
| Paraphrase robustness (headline estimates, 2 paraphrases) | $1.10 | $1.30 |
| Autoresearch feature loop | $0.50 | $0.80 |
| Discovery lane and spike | $1.00 | $1.00 |
| **Reserve (retries, unknown charges, reruns)** | | **$9.00** |
| **Total** | **$13.50** | **$25.00** |

These are estimates from one smoke call. The pilot replaces them with measured cost per
question, and each question must be worth its price. The guard enforces an
account-wide $25 total, counts unknown charges at worst case, and refuses any batch that
could cross the cap.

## 7. Human labels (~1,000, about 6 to 8 hours)

| Use | Labels |
|---|---|
| Screen calibration and PPI gold (known-probability draws, 30% uniform) | 400 |
| Deep-facet audit (workaround, paid/switched, resolved) | 150 |
| Assignment audit | 200 |
| Merge audit | 50 |
| Top-card review and "worth interviewing" | 200 |

## 8. Pre-registered success criteria

Written before any main-run result is seen:

- At least 3 cards with 10 or more distinct authors, 3 or more periods, 2 or more
  domains, no thread above 30% of matches, confirmed on the confirm half.
- Screen recall of at least 0.85 at the chosen threshold, from the held-out gold labels.
- Assignment precision of at least 0.75 on the audit.
- Planted-needs test: at least 90% of planted comments land on the right card.
- Every published number has a PPI interval, a denominator, a run ID, and a claims-ledger
  entry.
- Decision metric: 10 interviews booked from the X thread within 30 days. Impressions
  are not the target.

If nothing passes, the thread reports the method, Jev's measured accuracy and cost, and
the null result.

## 9. Validation experiment (smallest test of the core assumption)

**Core assumption:** Jev can turn comments into need-card assignments that match
Hansel's judgment.

**Test.** Inside the $0.50 pilot:
- screen 2,000 comments;
- draft 30 cards from the explore half;
- assign the pilot's firsthand problems;
- run the planted-needs test;
- have Hansel audit 100 assignments (about 40 minutes).

**Pass:**
- assignment precision of at least 0.75
- planted recovery of at least 90%
- residue under 40% after one induction round

**Fail:** redesign steps 3 to 5 before spending more. The loss is at most $0.50 and one
evening.

## 10. Decision

Adopt the Jev-first need-card pipeline with stratified sampling and PPI inference, a
hard $25 cap, and the pilot above as the go/no-go gate. Implementation goes to Devin
lanes (Fusion Opus 5.5 High + SWE-2 High).

## Sources

Checked 2026-09-29.

- Angelopoulos et al., "Prediction-Powered Inference," Science 2023, arXiv 2301.09633
- Angelopoulos, Duchi, Zrnic, "PPI++," arXiv 2311.01453
- Fisch et al., "Stratified Prediction-Powered Inference," NeurIPS 2024, arXiv 2406.04291
- Kluger et al., "PPI with Imputed Covariates and Nonuniform Sampling," arXiv 2501.18577
- Egami, Hinck, Stewart, Wei, "Using Imperfect Surrogates for Downstream Inference (DSL)," arXiv 2306.04746
- Baumann et al., "Large Language Model Hacking," arXiv 2509.08825
- Timoshenko, Mao, Hauser, "Transforming the Voice of the Customer," arXiv 2503.01870
- Tamkin et al., "Clio," arXiv 2412.13678
- Wan et al., "TnT-LLM," arXiv 2403.12173
- Pham et al., "TopicGPT," NAACL 2024
- Wang, Shang, Zhong, "Goal-Driven Explainable Clustering," EMNLP 2023
- Bernal, Cummins, Gasparrini, "Interrupted time series regression," IJE 2017
- Nielsen, "Participation Inequality: The 90-9-1 Rule," NN/g 2006
- Graham, "How to Get Startup Ideas," 2012; YC Startup School recap (Hale, Migicovsky), 2019
- TypeSafe cookbooks: hierarchical classification, entity alignment, re-ranking,
  autoresearch feature discovery, classification using confidence (docs.typesafe.ai)

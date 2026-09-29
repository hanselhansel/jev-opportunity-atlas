# Findings draft for Hansel's review (not published)

Status: draft. Nothing here is public until Hansel approves it. Every number traces to a run ID in `configs/run_phases.toml` and to the site tables built from `main-cards-final2-t3` with 2,000 bootstrap draws (seed 0).

## 1. What we measured

- **Window:** 2025-09-28 to 2026-09-28. That is 3,991,507 comments, of which 3,680,002 are eligible.
- **Screen:** Jev screened a stratified probability sample of 605,125 comments for "the writer describes a problem they hit themselves."
- **Facets:** Jev faceted 80,022 of the screen positives and a check sample below the cutoff (two waves, stratified, weights w1/p2). Of those, 70,561 are firsthand accounts.
- **Cards:** Claude drafted 150 need cards in 13 groups from explore-half pain sentences. Jev assigned every firsthand problem to a card (two-level choice, "none of these" allowed).
- **What the numbers are:** shares of HN firsthand complaints, as classified by Jev. They are not market demand.

## 2. Headline numbers

| Claim | Number |
|---|---|
| HN comments that describe a problem the writer hit | about 6 to 8% (7.6% original wording; 7.1% and 5.9% under two rewordings) |
| Share of firsthand problems that fit one of the 150 cards | 58% (42% are one-offs or too vague) |
| Largest single card | 2.0% of firsthand problems ("Broken, slow websites") |
| AI-related problems (3 AI groups) | 11.0% of firsthand problems over the year, up from 9.0% in H1 to 13.0% in H2 |
| Problems still open after replies (top 15 cards) | about 2 in 3 had no reply naming a fix and no "solved" from the author |

## 3. Where the problems are (need groups, share of firsthand problems, 95% interval)

| Group | Year | H1 | H2 | Change (p adj) |
|---|---|---|---|---|
| Dev tools and languages | 11.0% [10.4, 11.6] | 12.4% | 9.7% | -2.7 (0.003) |
| OS, devices, hardware, cars | 9.3% [8.8, 9.9] | 10.9% | 7.9% | -3.0 (0.003) |
| Consumer apps and shopping | 6.3% [5.8, 6.8] | 6.2% | 6.4% | no clear change |
| AI coding tools | 5.1% [4.7, 5.5] | 4.5% | 5.7% | +1.2 (0.003) |
| AI chatbots and models | 4.8% [4.4, 5.2] | 3.7% | 5.9% | +2.2 (0.003) |
| Health and personal life | 4.1% [3.8, 4.5] | 4.2% | 4.0% | no clear change |
| Security, privacy, scams | 4.0% [3.7, 4.4] | 3.5% | 4.5% | +1.0 (0.022) |
| Cloud and ops | 3.9% [3.5, 4.3] | 4.5% | 3.3% | -1.2 (0.013) |
| Money, housing, travel | 2.6% [2.3, 2.9] | 2.4% | 2.7% | no clear change |
| Online communities | 2.5% [2.2, 2.9] | 2.2% | 2.9% | +0.7 (0.049) |
| Jobs and running a company | 2.3% [2.1, 2.6] | 2.4% | 2.3% | no clear change |
| AI effects on work and web | 1.1% [1.0, 1.3] | 0.8% | 1.4% | +0.6 (0.003) |
| Learning and schools | 0.4% [0.4, 0.6] | 0.3% | 0.5% | no clear change |

H1 is 2025-09-28 to 2026-03-28. H2 is 2026-03-28 to 2026-09-28. The p-values are BH-adjusted across the 13 groups. Every significant group change survives dropping its largest thread.

## 4. The cards that moved (H2 minus H1, p adj < 0.05)

**Rising, all AI:**

| Card | H1 | H2 |
|---|---|---|
| AI coding costs and limits | 0.58% | 1.10% |
| AI plans and terms change | 0.24% | 0.69% |
| Chatbots flatter and pad | 0.29% | 0.70% |
| Models refuse requests | 0.27% | 0.64% |
| AI erodes skill and joy | 0.12% | 0.43% |
| Model quality slips | 0.15% | 0.42% |
| Local models slow or fiddly | 0.14% | 0.39% |
| AI cuts pay for skilled work | 0.06% | 0.16% |

**Falling:**

| Card | H1 | H2 |
|---|---|---|
| Desktop Linux gaps | 1.90% | 0.79% |
| Steep languages, poor docs | 2.29% | 1.51% |
| Updates break devices | 1.86% | 1.10% |
| Rebuilding small tools | 1.01% | 0.53% |
| Legacy code slows change | 0.93% | 0.51% |
| Keyboards and autocorrect | 0.67% | 0.28% |
| Senior engineers can't find jobs | 0.37% | 0.12% |

**Flags:**
- Three cards lean on one thread for over 10% of their matches: "AI cuts pay for skilled work" (19%), "Chatbots flatter and pad" (10%), "Keyboards and autocorrect" (11%). Their changes shrink, but hold, when that thread is dropped.
- A falling share can mean that other topics grew. These are shares of complaints, not counts.

## 5. Opportunity read (Claude's, for Hansel to judge)

These combine share, growth, commercial signal from the facets (already paying, switching, or giving up; money cost), and replies.

1. **AI coding costs and limits.**
   - Share doubled, from 0.58% to 1.10%.
   - 41% already pay, switch, or give up, and 34% name a money cost. Both are the highest among the top 40 cards.
   - 66% are unsolved in replies.
   - Clearest paid pain in the set.
2. **AI plans and terms change.** Nearly tripled (0.24% to 0.69%). This is people planning around shifting quotas, credits, and model access.
3. **Agent reliability.**
   - "AI agents write bad code" is 1.6% of firsthand problems, 77% unsolved in replies, with the highest severity among top cards.
   - "AI agents lose track" is 0.9%.
   - "Buggy AI editor tools" is 0.7%, 63% unsolved.
   - Flat in share, large, and mostly unsolved.
4. **Local models slow or fiddly.** 0.14% to 0.39%. A duplicate card (n136, "Local models too slow") holds another slice; see decision 2.
5. **Early failure, no repair.** 0.8%. 37% already pay, switch, or give up, and 25% name a money cost.

Workaround-heavy cards (people build their own) are "Rebuilding small tools" (59%), "TVs and gear misbehave" (57%), and "Fragile shell setups" (52%). The first is falling.

## 6. How Jev did (the Jev story)

| Item | Result |
|---|---|
| Total credit used | $21.48 calculated, over 461,843 calls, across 23 runs |
| Screen of 605,125 comments | $7.05, 2 h 19 min, p50 260 ms, p95 335 ms (packed 5 per call) |
| Facets on 80,022 comments (18 questions each) | $6.17 |
| Card assignment and checks | about $6.7 |
| Blind human audit of card fit (pilot) | Jev 95% vs random same-group card 60% (n = 31 and 26) |
| Synthetic benchmark (226 invented cases) | 97.8% screen accuracy, 98.2% recall. Weak on product pitches (75%) and sarcasm (83%) |
| Planted-needs test | 90% of planted comments recovered, 0% of decoys misplaced |
| Card assignment under reworded instructions | 91 to 92% same card, 95% same group, top-20 shares move under 0.4 points |
| Membership check (yes/no "does this card fit") | 71% of assignments confirmed. Stricter than the audit |
| Unknown-charge attempts | 95 of about 462k, counted at worst case |

**Costs I got wrong:**
- Card-level calls came in 1.3 to 1.4 times over estimate.
- The membership check came in 2.0 times over estimate.
- The merge check first stopped silently at its cap. It is fixed and now fails loudly.

## 7. Caveats to state publicly

- HN is not the market. These are HN commenters, who skew toward developers.
- All numbers are as classified by Jev. Only card fit had a human audit, on the pilot (31 items). Screen calibration has 6 valid human labels, too few for a correction, so prevalence is Jev-classified with a wording range.
- The screen misses firsthand accounts below the cutoff. About 19% by weight of the below-cutoff check sample read as firsthand. Card shares describe the problems the screen caught.
- 42% of firsthand problems fit no card. The cards describe the recurring part, not everything.
- A second induction round was skipped. Budget was the reason, and round one moved the residue only 4.6 points.

## 8. Decisions for Hansel

1. Approve or edit the headline claims in sections 2 to 5.
2. Duplicate card: merge n136 "Local models too slow" into n014 "Local models slow or fiddly"? Merge scoring flagged 11 pairs. Only this one is a true duplicate in my read. Merging adds about 0.1 point to n014 and needs a t4 version bump.
3. Approve the chart titles in `configs/x_titles.toml`.
4. Approve or edit the X thread below.
5. Go for release: pack, restore test, Pages dry run, then push.

## 9. Draft X thread (Hansel's voice)

1/ I had a cheap classifier read a year of Hacker News comments. 605,125 of them. Total cost: $21.48.

Here is what people on HN say is broken in their own work and life.

2/ About 6 to 8% of HN comments describe a problem the writer hit themselves. The number moves with how you ask, so I report the range.

3/ No single problem dominates. The biggest one, broken and slow websites, is 2% of all firsthand complaints. It is a long tail.

4/ The shift is AI. AI-related complaints went from 9% to 13% of all firsthand problems between the first and second half of the year. Classic dev tooling and device complaints fell.

5/ The fastest riser: the cost of AI coding tools. Token bills and usage limits doubled their share. 41% of those comments say the writer already pays, switched, or gave up. That is the clearest paid pain in the data.

6/ Also rising: AI plans and terms that keep changing, chatbots that flatter, models that refuse, and people who feel AI is eroding their skill.

7/ Method: stratified sample, Jev for every classification step, 150 need cards drafted by Claude, a blind human audit (Jev 95% vs random 60%), planted-needs test (90%), reworded-question checks. Every number has an interval and a run ID.

8/ Everything is public: code, run manifests, IDs, and a replay script. No comment text ships. The site links each finding to its evidence.

Link: <site URL after release>

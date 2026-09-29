# Story design: "Startup opportunities identified via Hacker News conversations between 2025-26"

Status: approved in brainstorming with Hansel on 2026-09-30. The story and its key charts come first. The polished atlas page comes later.

## Reader and form

- **Primary reader:** founders and would-be founders looking for problems worth building for.
- **Secondary reader:** data practitioners who want to trust and reuse the method.
- **Form:**
  - a long-form scrolling essay, one reading column, full-width charts;
  - each section runs question, then chart, then interpretation, then a "for a builder" line;
  - X carries an 8 to 10 post trailer that links to the essay.
- **Draft vehicle:** a private interactive claude.ai artifact built only from aggregate numbers. It is ported into the atlas site later.
- **Writing rule:**
  - every sentence and bullet is 15 words or fewer;
  - Hansel's voice rules apply (no em dashes, no banned words);
  - no HN quotes, only numbers, charts, and links to evidence.

## First-principles frame

A problem is a startup opportunity only if six things are true. Each chapter tests one.

| Must be true | Chapter | Measure |
|---|---|---|
| Many people hit it | 1 | share of firsthand problems (card_share) |
| It hurts more than talk suggests | 2 | complaint share vs discussion share, by domain |
| It is growing | 3 | H2 minus H1 change; monthly share heat map |
| People spend to cope | 4 | paid, switched, abandoned, workaround, money-cost rates |
| Existing fixes fall short | 5 | unsolved rate from replies; named fixes; author follow-ups |
| Few build for it | 5 | Show HN launch share per card vs complaint share |

Chapter 6 combines the six into an opportunity score. The weights are visible and adjustable.

## Outline

**How to read this.** Four short paragraphs:
- what we did;
- what the numbers are (shares of HN complaints, not market size);
- the six questions.

**0 · The raw material.** A funnel chart: comments in window (3.99M), eligible (3.68M), screened by Jev (605k), firsthand problems faceted (70.6k), matched to a card (58%).

**1 · What people complain about.** About 7% of comments (6 to 8% by wording). Group shares with intervals.
- **Deep dives:**
  - the 150 problems ranked;
  - roles who hit each group (user_role facet);
  - domain clusters (the problem × domain matrix).

**2 · Loud vs quiet.** A scatter of each domain's share of all comments (x) against its share of firsthand problems (y), with a diagonal reference line. Above the line means a pain-heavy topic.
- **Data:** the domain facet on the phase-2 pos rows and on the 2,022 below-cutoff check rows, weighted.
- **Deep dive:** complaint intensity (y / x) ranked, with intervals.

**3 · What changed.**
- **Charts:**
  - a month × group heat map of share (P01 to P12);
  - risers and fallers (card_change, p adj < 0.05).
- **Deep dives:**
  - what stayed on top regardless of trend;
  - the thread-concentration check (drop the top thread) on every claimed change.

**4 · Pay, work around, give up.** For the top 40 cards: workaround rate and max(paid, switched, abandoned) rate as a two-axis scatter, sized by share.
- **Quadrants:** "people pay" (high commercial) vs "people hack" (high workaround).

**5 · Is anyone solving it?**
- **(a)** Unsolved rate per card from the replies check, top 40 cards.
- **(b)** Named fixes: top recommended tools per card, and tools named inside complaints ("who gets blamed").
- **(c)** Builders vs complainers: each card's share of Show HN launches (x) against its share of complaints (y). Far above the line means lots of pain and few launches.

**6 · Where the openings are.** An opportunity map:
- x is growth (H2 minus H1), y is share, bubble color is the unsolved rate;
- the bubble outline marks few builders;
- a ranked shortlist of 5 to 8 cards, each with a profile card: signals, trend, named fixes, builder count, confirm-half status.
- **Interactive:** weight sliders re-rank the list. Clicking a card opens its profile.

**How we know.**
- the method in plain words;
- the Jev story: total cost, calls, speed, and cost per step;
- accuracy: audit 95% vs 60%, benchmark, planted test, wording robustness.

**What could be wrong.** HN is not the market. Classification error. Screen misses. 42% residue. Thin human labels.

## New data

1. **Replies, top 40 cards.** Run the existing `cards replies --top-cards 40` on `main-cards-final2-t3`. About $0.25 (budget `replies`).
2. **Named fixes (new command).**
   - Claude curates about 300 products and companies with categories in `configs/tools.v1.yaml`: name, aliases, category.
   - Code matches the dictionary against problem comments and their direct replies, locally, in `data/`. Nothing tracked holds text.
   - Jev confirms each reply hit with one yes/no: "Does this reply recommend <tool> as a fix for <problem>?"
   - Hits inside problem comments are reported as "named in complaints" (no Jev call).
   - About $0.20, new budget `solutions`.
3. **Builders on Show HN (new command).**
   - Draw a random sample of 8,000 of the 46,070 in-window Show HN stories, stratified by month.
   - Assign each to the t3 cards with launch-framed instructions: "Which need does this product address?"
   - The input is the title plus up to 300 characters of story text.
   - Weights come from the sample, so shares carry intervals.
   - About $0.60, new budget `builders`.
4. **Budget moves (Hansel approved the A+B+C spend on 2026-09-30):**
   - `discovery` goes from 0.80 to 0.00, and `robustness` from 1.30 to 0.95;
   - `replies` goes from 0.30 to 0.65;
   - add `solutions = 0.30` and `builders = 0.70`.

## Computation (no Jev)

A `story data` command writes one aggregate JSON (plus Parquet twins) with every number the essay uses:

- funnel counts;
- group and card shares (all, H1, H2, per month);
- domain discussion vs complaint shares;
- per-card facet rates;
- unsolved rates;
- named-fix tallies;
- builder shares;
- opportunity components;
- runs and cost;
- quality and robustness.

Every number carries its n, its interval where one applies, and a run ID. No text and no usernames. Labels come from `configs/cards/main.t3.labels.yaml`.

## Opportunity score

- **Components:**
  - share;
  - growth;
  - unsolved rate;
  - commercial rate;
  - severity;
  - builder gap = complaint share minus launch share.
- **Normalization:** min-max within the scored cards.
- **Weights:** equal by default in `configs/story_weights.toml`, and adjustable in the draft.
- **Confirmation:** only cards that pass the pre-registered criteria on the confirm half can enter the shortlist.

## Testing and review

- Every new command gets tests with the mock transport. The story JSON goes through the text gate.
- Claude checks each chart visually against the numbers before Hansel sees the draft.
- Hansel reviews the draft artifact, then the X trailer, before anything is public.

## Out of scope for this spec

- porting into the atlas site (a later plan);
- quotes;
- a second induction round;
- new screen or facet runs.

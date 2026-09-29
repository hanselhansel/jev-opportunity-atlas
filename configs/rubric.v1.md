---
version: v1
status: approved
approved_by: Hansel
approved_at: 2026-09-28T20:20:00Z
---

# Labeling rubric v1

You see one Hacker News comment at a time, with its story title and the comment it
replies to. You never see Jev's answer. Judge only what the text says. When the text
does not settle a question, choose **unsure** rather than guessing.

Examples below are made up to show the rule. They are not real comments.

## Question 1: firsthand_problem

**Does the comment describe a problem, difficulty, or frustration that the author
personally experienced?**

**Yes** when all three hold:

1. There is a problem: something that failed, blocked, cost time or money, confused, or
   frustrated.
2. The author experienced it: "I", "we", "my team", "our company", "at my job", or the
   context makes clear it happened to them.
3. It is stated as fact, not as a hypothetical ("if I ever...", "imagine...").

**No** when any of these hold:

- No problem is described (praise, news, a neutral fact, a joke with no real complaint).
- The problem belongs to someone else ("my friend's startup...", "users report...").
- It is general opinion ("this API design is bad") with no sign the author hit it.
- It is a sales pitch for the author's own product, even if it names a problem.

**Unsure** when the author might be describing their own experience but the text does
not say so, or sarcasm makes the literal meaning unclear.

| Example | Label | Why |
|---|---|---|
| "We lost two days last month because our CI cache silently served stale builds." | yes | Named problem, the author's team, stated as fact |
| "I tried three invoicing tools and none handle multi-currency refunds." | yes | Own experience, concrete gap |
| "How do people deal with flaky Postgres failovers? Ours drop writes every few weeks." | yes | A question, but it states the author's own problem |
| "This is why I never use ORMs." | no | Opinion; no experienced problem described |
| "Kubernetes is too complex for small teams." | no | General claim |
| "My cousin's clinic still faxes lab results." | no | Someone else's problem |
| "We built Acme to fix exactly this, try it free." | no | Pitch |
| "Oh great, another outage, love it." | unsure | Sarcasm; unclear if the author was affected |

Borderline rules:

- A problem the author says is now solved still counts as **yes**. Resolution is a
  separate question.
- A past problem counts as **yes** if the author experienced it. Timing is a separate
  question.
- A question asking for help counts as **yes** only when it states the author's own
  problem.
- "We" as a company or team counts. "We" meaning "people in general" does not.

## Question 2: account_type

**What kind of text is the comment?** Pick the single best fit.

| Option | Use when | Example |
|---|---|---|
| firsthand_account | The author describes their own experience | "At my last job we migrated off Heroku and our bill tripled." |
| secondhand_report | The author reports what happened to someone else | "A friend's agency got banned from Google Ads with no reason given." |
| general_opinion | A view or argument without a personal account | "Microservices are overused." |
| product_pitch | Promotes a product, service, or project the author is connected to | "I built a tool for this, link in profile." |
| joke_or_sarcasm | Humor or sarcasm, not meant literally | "Just rewrite it in Rust, obviously." |
| question_or_request | Mainly asks a question or for help or recommendations | "Any good alternatives to Jira for a 5 person team?" |
| other | None of the above | A bare link, a correction of a typo |

Tie-breaks:

- A question that describes the author's own problem is **question_or_request** here,
  and still **yes** on question 1.
- A pitch that opens with a personal story is **product_pitch**.

## Question 3: domain (only on the items where it appears)

**What area is the main subject of the comment?** Use the same options Jev sees:
software_development, infrastructure_ops, data_ml_ai, security_privacy, product_design,
business_operations, finance_payments, sales_marketing, work_careers, legal_government,
hardware_electronics, consumer_tech, health_medical, education_learning,
science_research, media_publishing, home_life, other, mixed, unclear.

Pick the subject of the comment, not the story. Use **mixed** when two areas matter
equally, and **unclear** when you cannot tell.

## How labeling works

- Sessions of 45 minutes or less. Stop when tired; progress is saved.
- About 10% of items come back later unannounced, to measure consistency.
- Median time per item should be 20 to 30 seconds. If an item needs more than a minute,
  choose unsure and move on.

## Audit: facet_audit

You see a comment (plus its parent and story) and answer the facet questions from
the text alone. You never see Jev's facet labels. Each of the first six questions
asks whether the comment states that something happened to the author:

- **workaround**: the author describes a workaround, hack, or manual process they use
  for the problem.
- **paid**: the author pays for something to deal with the problem.
- **switched**: the author switched tools or vendors because of the problem.
- **abandoned**: the author gave up on a tool or the task because of the problem.
- **cost_time**: the problem costs the author time.
- **cost_money**: the problem costs the author money.

Pick **yes** only when the comment states the thing happened to the author. Pick
**no** when the text does not mention it or it happened to someone else. Pick
**unsure** when the text hints at it but does not say so plainly.

- **resolution**: using the comment and its parent only, is the author's problem
  solved? **resolved** when the comment says so or describes the fix that worked,
  **unresolved** when the problem is still open, **unclear** when you cannot tell.

| Example | workaround | paid | resolution |
|---|---|---|---|
| "Every Friday I export the report to CSV and fix the dates by hand." | yes | no | unresolved |
| "We ended up paying for a managed queue just to stop losing jobs." | no | yes | resolved |
| "My teammate wrote a script for this, works fine." | no | no | resolved |

Borderline rules:

- A workaround someone else describes does not count as the author's.
- "I would pay for this" is a wish, not **paid**; pick **no**.
- A problem stated without any mention of how it ended is **unresolved** only when
  the text makes clear it is still open; otherwise **unclear**.

## Audit: assignment_audit

You see a pain sentence from a comment and one candidate need card. Judge only
whether the need describes the problem in the comment. The shown need may or may
not be the model's pick; you are not told which. Do not try to guess which it is.

- **yes**: the need card states the problem in the sentence, at about the same scope.
- **partly**: the need overlaps the problem but is broader, narrower, or covers only
  part of it.
- **no**: the need is about a different problem.
- **unsure**: the sentence or the card is too vague to judge.

| Pain sentence | Need card | Label | Why |
|---|---|---|---|
| "I spend an hour a day reformatting invoices." | "Invoices require manual rework" | yes | Same problem, same scope |
| "Our cron jobs silently stop after deploys." | "Deploys break scheduled jobs" | yes | Same problem |
| "I lost a customer over a missing invoice." | "Invoices require manual rework" | partly | Related to invoices, different problem |
| "The VPN drops my calls twice a day." | "Deploys break scheduled jobs" | no | Different problem |

Borderline rules:

- Judge the need statement, not whether the comment is well written.
- A card that is a superset of the problem (same issue plus more) is **partly**.
- When the sentence names a symptom the card does not mention, pick **no** unless
  the link is direct and stated.

## Audit: merge_audit

You see two need statements, A and B. Judge how they relate. You never see card ids
or the model's score.

- **same**: a person with problem A has problem B; the statements describe one
  underlying problem at the same scope.
- **related**: the problems are distinct but overlap or sit side by side, so
  comments about one often mention the other.
- **different**: the statements describe separate problems.

| Need A | Need B | Label | Why |
|---|---|---|---|
| "Invoices need manual rework" | "Billing documents require hand edits" | same | One problem, two phrasings |
| "Deploys break scheduled jobs" | "Scheduled jobs lack monitoring" | related | Same area, different problems |
| "VPN calls drop daily" | "Invoices need manual rework" | different | Unrelated |

Borderline rules:

- Different wordings of the same problem are **same**, even if one is more general.
- Sharing a tool or vendor is not enough for **same**; pick **related**.
- When a relationship might exist but neither statement says so, pick **different**.

## Review: interview

This is a judgment review, not a blind check. You see a top need card with its
group, its metrics (authors, threads, periods, domains), and up to five example
pain sentences from comments linked to it. The metrics are shown on purpose.
Decide whether the card is worth a customer interview.

- **strong**: a distinct, painful problem with enough independent voices to make an
  interview worth scheduling now.
- **maybe**: promising, but thin evidence, unclear scope, or weak example sentences.
- **no**: too narrow, too vague, duplicate of a better card, or not a real problem.

The **why** note is optional, at most 280 characters. Use it to flag duplicates or
to note which example sold the card.

| Card sketch | Label | Why |
|---|---|---|
| Many authors, several threads, concrete examples | strong | Repeated, specific pain |
| Few authors, vague statement | maybe | Needs more evidence |
| One thread, metric line dominated by a single source | no | Thin or duplicate |


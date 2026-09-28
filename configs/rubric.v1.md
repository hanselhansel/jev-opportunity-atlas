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

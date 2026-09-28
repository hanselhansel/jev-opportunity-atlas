---
status: draft
version: v1
---

# Labeling rubric v1

Read this before every labeling session. Label from the comment text, using the parent and
story title only as context. Do not open the HN link to look at replies or votes unless the
comment is unreadable without it. All examples below are synthetic.

Sessions last 45 minutes or less. If you are unsure after 30 seconds, pick `unsure` (for
`firsthand_problem`) or your best option and move on.

## firsthand_problem

**Question.** Does the comment describe a problem, difficulty, or frustration that the
author personally experienced?

- `yes`: the author says they themselves ran into the problem. First person includes "I",
  "we", "my team", "our company", "at my job".
- `no`: no problem is described, or the problem belongs to other people, is hypothetical,
  is a general opinion, or is a sales pitch.
- `unsure`: the text does not let you decide. Use it rarely. Unsure labels are dropped from
  precision and recall and counted separately.

Borderline rules:

1. A question asking for help counts as `yes` when it states the author's own problem
   ("Our CI takes 40 minutes, how do I speed it up?"). A bare question with no stated
   problem is `no`.
2. Sarcasm about one's own tool counts only when the problem is literal. "I love how my
   laptop fan screams every time I open Slack" is `yes` (the fan noise is real). "Sure, I
   will just rewrite the kernel this weekend" is `no`.
3. A problem the author says is solved still counts as `yes` ("We lost a week to flaky DNS
   last year until we moved resolvers").
4. A problem at the author's employer that the author took part in counts as `yes`. A
   story about a friend's company is `no`.
5. A founder describing the problem their product solves is `no` unless they describe
   hitting it themselves before building the product.

Examples:

- `yes`: "I spent two days trying to get the SDK to authenticate behind our corporate
  proxy."
- `no`: "Most companies underinvest in documentation, and it shows."
- Borderline, label `yes`: "Anyone else seeing timeouts from the billing API since
  Monday? Our checkout has failed about 3% of the time."

## account_type

**Question.** What kind of text is the comment? Pick the one option that fits the main
purpose of the comment.

- `firsthand_account`: the author describes their own experience.
- `secondhand_report`: the author reports what happened to someone else.
- `general_opinion`: a view or argument without a personal account.
- `product_pitch`: promotes a product, service, or project the author is connected to.
- `joke_or_sarcasm`: humor or sarcasm, not meant literally.
- `question_or_request`: mainly asks a question or asks for help or recommendations.
- `other`: none of the above.

Tie rules: a help request that opens with the author's own story is
`question_or_request` when the ask is the main point, `firsthand_account` when the story is.
A pitch framed as a personal story is `product_pitch`. `firsthand_problem` and
`account_type` are labeled independently: a `question_or_request` can still be a `yes`.

Examples:

- `firsthand_account`: "We moved our build to a single large machine and cut CI time from
  25 to 6 minutes."
- `general_opinion`: "Microservices are mostly an org chart problem, not a technical one."
- Borderline, label `product_pitch`: "I had the same problem with invoices, which is why I
  built a small tool for it (link in profile)."

## domain

Shown only on a seeded subset of the calibration queue. Pick the area that is the main
subject of the comment, using the options in `configs/questions/screen.v0.json`. Use
`mixed` when two areas are equally central and `unclear` when the text does not say.

Examples:

- `infrastructure_ops`: "Our Kubernetes nodes kept getting evicted during peak traffic."
- `finance_payments`: "Reconciling payouts across two payment processors takes me a day a
  month."
- Borderline, label `mixed`: "We could not ship the mobile app because the payment SDK
  broke our iOS build."

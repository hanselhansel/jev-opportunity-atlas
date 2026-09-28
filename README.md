# Jev Opportunity Atlas

What problems do people on Hacker News keep running into? This project reads one year of
HN comments (28 Sep 2025 to 28 Sep 2026), uses TypeSafe's Jev model to flag firsthand
problem reports, and turns the recurring ones into startup hypotheses you can inspect
down to the original comment.

It is also a public test of Jev: how accurate it is against blind human labels, what it
costs, and how fast it runs. Every number comes from a saved run and can be replayed
without calling HN or Jev.

**Status:** work in progress. No findings yet. The HN corpus is being collected.

**Disclosure:** no affiliation with TypeSafe. I paid for all usage.

## What this is and is not

- Findings are hypotheses about what HN commenters report. They are not evidence of
  market size, demand, or willingness to pay.
- Two evidence lanes stay separate: a probability sample (for proportions) and targeted
  searches (for depth, never for proportions).
- Jev answers typed yes/no, choice, and score questions. It does not write text. Category
  names are proposed with help from Claude and approved by me; that is disclosed wherever
  it applies.

## Data and rights

HN comments belong to their authors. This repo does not redistribute comment text.
Public releases contain comment IDs, model answers, hashes, and aggregates, plus a script
that re-fetches text from the [official HN API](https://github.com/HackerNews/API).
Findings quote short passages with links. Code is MIT licensed; derived labels and
aggregates are CC BY 4.0.

## Setup

```bash
brew install gitleaks          # required by the local verify gate
uv sync
git config core.hooksPath .githooks
scripts/verify.sh              # gitleaks, ruff, pytest
```

The Jev key is read from macOS Keychain (service `typesafe-jev-api-key`) or the
`TYPESAFE_API_KEY` environment variable. It is never stored in the repo.

## Design

- Design: `docs/superpowers/specs/2026-09-29-jev-opportunity-atlas-design.md`
- Plans: `docs/superpowers/plans/`
- Plan review: `docs/reviews/2026-09-29-plan-review.md`

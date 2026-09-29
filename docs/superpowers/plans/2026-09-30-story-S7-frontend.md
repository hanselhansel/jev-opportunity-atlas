# S7: Essay front-end (static, interactive, from story.json)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` (the contract) and `docs/superpowers/specs/2026-09-30-story-visuals.md` (the per-chart designs) first.

Branch: feat/s7-essay-frontend

**Goal:**
- A static page `essay/index.html` that renders the essay from `essay/data/story.json` and `essay/content/story.md`.
- Each chapter has its interactive charts, built against a synthetic fixture that follows the contract.

**Files you own:**
- `essay/index.html`, `essay/app.js`, `essay/style.css`
- `essay/lib/glyph.js` (the interval glyph and certainty fade), `essay/lib/sheet.js` (the bottom detail sheet), `essay/lib/palette.js`, `essay/lib/md.js` (a tiny markdown-to-HTML renderer: headings, paragraphs, bold, lists, and `<!-- chart:<id> -->` placeholders)
- `essay/charts/*.js` (one file per chart)
- `essay/fixtures/story.fixture.json`, `essay/content/story.fixture.md`
- `essay/test/*.test.mjs` (run with `node --test`), `scripts/essay-check.sh`

**Rules:**
- ES modules only, with no bundler.
- D3 v7, `@observablehq/plot@0.6`, `d3-voronoi-treemap`, and `scrollama` from cdn.jsdelivr.net, pinned versions.
- Everything else inline.
- Colors are CSS tokens on `:root` with a dark-mode override.
- Works at 375 px with no horizontal scroll. Honors `prefers-reduced-motion`.
- UI copy follows the 15-word rule.

**Chart modules and their story.json sources:**

| File | Chart | Source keys |
|---|---|---|
| `funnel-units.js` | zooming unit field, 1 dot = 1,000 comments, steps from `funnel.steps`, monthly bars | `funnel` |
| `voronoi-needs.js` | Voronoi treemap: 13 groups, 150 cells, a grey "not placed" sector | `groups, cards, unplaced` |
| `forest-top.js` | forest plot of the top 30 cards, interval glyph, counts columns | `cards[].share, n_*` |
| `terms-columns.js` | distinctive terms, 13 small columns | `terms` |
| `role-mekko.js` | marimekko: width = group share, height = role mix | `groups, roles` |
| `domain-morph.js` | domain bubbles: discussion to complaints, morphing into a complaint-rate lollipop | `domains` |
| `breadth-swarm.js` | beeswarm of card entropy, expandable residual matrix | `cards[].breadth` |
| `need-stripes.js` | 13 groups × 4 quarters (months toggle), diverging color, certainty fade | `groups[].quarters, months` |
| `risers-fallers.js` | difference plot of cards with p_adj < 0.05, shrunk dot and raw tick | `cards[].change` |
| `coping-triangle.js` | guided build: three bars, normalize, collapse to a ternary dot | `cards[].coping` |
| `cost-radar.js` | outline-only radar small multiples per group, whiskers, heat-table toggle | `cards[].costs` (group-weighted) |
| `builders-scatter.js` | log-log complaint share vs launch share, diagonal, underbuilt zone | `cards[].builders, share` |
| `closed-open.js` | 100-unit waffle opener, then aligned columns for the top 40 | `cards[].unsolved` |
| `tool-funnel.js` | tool threads vs fix share with funnel bounds | `tools` |
| `opportunity.js` | explorer: presets, sliders, contribution bars, rank quantile dots, top 10 strip | `cards[].score, score_presets` |
| `bundles.js` | bundle cards plus an edge-bundled circle | `bundles, edges` |
| `profile.js` | opportunity profile card in the bottom sheet | all card fields |
| `mindmap.js` | "Find your need" radial tree drawer, follow-this-card mode | `groups, cards` |
| `receipt.js` | a 2,148-cent grid by phase, plus calls-vs-cost slope bars | `method` |
| `quality.js` | 100-unit arrays for the audit, benchmark, planted test; wording range bars | `method` |
| `spec-ranks.js` | rank range strip | `spec_ranks` |
| `concentration.js` | funnel plots for threads and authors | `cards[].concentration` |

## Task 1: Shell, reading system, content rendering
- [ ] **Test (node):**
  - `md.test.mjs` renders headings, paragraphs, lists, and chart placeholders;
  - `glyph.test.mjs` maps an Est to the 50% and 95% bar extents, and fades when `sparse`.
- [ ] Implement `index.html` and `app.js`:
  - load `data/story.json`, falling back to `fixtures/story.fixture.json` when absent;
  - render `content/story.md`, falling back to the fixture markdown;
  - mount a chart at each placeholder;
  - the bottom sheet serves every chart's detail view;
  - the mind-map drawer is always reachable.
- [ ] Commit.

## Task 2: Chart modules
- [ ] Build each module in the table. Each exports `mount(el, story, api)`.
  - `api` offers `followCard(id)`, `openSheet(cardId)`, and `reducedMotion`.
  - Each module draws only from its source keys and shows "too few" for `sparse` estimates.
- [ ] **Test (node):** for each module, a pure `prepare(story)` function returns the render-ready rows. Test it on the fixture. Include:
  - `opportunity.test.mjs`: all-zero weights fall back to equal and set a notice flag;
  - `builders.test.mjs`: a zero-launch card is placed on the axis floor, marked "no sampled launch".
- [ ] Commit after every 3 to 4 modules.

## Task 3: Checks
- [ ] Write `scripts/essay-check.sh`. It runs `node --test essay/test`, serves `essay/` with `python3 -m http.server`, and uses headless Chrome (`--dump-dom`, virtual time budget 30 s) at widths 1280 and 375. It asserts:
  - every placeholder rendered a `<svg>` or `<canvas>`;
  - `document.documentElement.scrollWidth <= clientWidth`;
  - no console error text in the DOM error slot.
- [ ] Commit. `scripts/verify.sh` prints `verify: ok`, and `scripts/essay-check.sh` passes. Open the PR. Final message: PR URL, the node test summary, and the essay-check result.

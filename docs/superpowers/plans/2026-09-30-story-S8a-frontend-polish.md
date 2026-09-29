# S8a: Essay front-end polish from the real-data review

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md`, `docs/superpowers/plans/2026-09-30-story-S7-frontend.md`, and `docs/superpowers/specs/2026-09-30-story-visuals.md` first.

Branch: feat/s8a-essay-polish

**Goal:** Fix every defect found when the essay rendered real data. The real `essay/data/story.json` is not in git. Test against the fixture, and extend the fixture where a defect needs a data shape it lacks (for example `p_adj >= 0.05` on a rising card).

**Files you own:**
- `essay/**` except `essay/data/` and `essay/content/story.md` (the main session writes that)
- `scripts/essay-check.sh`

## Findings to fix (one test or check per item)

1. **Title and H1:**
   - The page H1 comes from the first `#` heading of `essay/content/story.md`. Never hard-code it.
   - The document `<title>` equals that H1.
2. **Funnel (`funnel-units.js`):**
   - Step labels overlap the dot field. Put labels in a left column that never overlaps the dots.
   - Mark `all` and `eligible` as "counted" and `screened` as "Jev read this sample". Mark `firsthand` and `placed` as "estimated for all eligible comments".
   - Build the zooming unit field from the visuals spec, with Scrollama: a 1,000-to-1 rescale at the sample step, and a static stacked fallback under reduced motion.
3. **Needs (`voronoi-needs.js`):**
   - Replace `d3.pack` with a real Voronoi treemap (`d3-voronoi-treemap`, seeded, 60 iterations) inside a circle.
   - Groups are regions and cards are cells. `unplaced` is a grey sector of the same circle, not a separate circle.
   - Show group labels (short) only where the region is large enough. Other labels go to hover or the sheet.
4. **Forest (`forest-top.js`):** the counts column clips at the right edge. Right-align within the container. At under 700 px wide, show only "problems / authors".
5. **Terms (`terms-columns.js`):**
   - Column headers truncate and overlap.
   - Use short group labels over 2 lines, or a group picker when the width is too small.
   - Remove the stray interval dots that overlap words. Draw each interval as a thin bar under its word.
6. **Role marimekko (`role-mekko.js`):**
   - Roles have no colors (all grey). Give the top 6 roles distinct palette colors and the rest grey, with a legend.
   - Bottom column labels overlap. Label only columns wider than 40 px and use hover for the rest.
7. **Human labels:** domain and role IDs render raw (`consumer_tech`). Map them through `story.labels.domains` and `story.labels.roles` (added by S8b). Fall back to title case with underscores turned into spaces.
8. **Need stripes (`need-stripes.js`):**
   - Every cell is the same orange, so the diverging scale is broken.
   - Color = log(quarter share / full-year share) on a diverging scale centered at 0 with symmetric limits. Test it with fixture values above and below the yearly share.
   - Row labels truncate. Use short labels.
9. **Cost radar (`cost-radar.js`):**
   - The shapes are too small. Set the shared radius max to the largest group rate, rounded up to 10%, and state it in the caption ("outer ring = 40%").
   - The axis header row is misaligned. Put the axis names on each radar.
10. **Builders scatter:** the y-axis title is clipped. Label the 8 most underbuilt cards (lowest ratio among cards with at least 100 problems) directly, with collision avoidance.
11. **Closed-open (`closed-open.js`):**
    - The opener shows "0% got a reported fix" because authors almost never report fixes.
    - Make the opener 100 units split into "a reply named a fix", "no reply fixed it", and "not checked". Use `unsolved` over the top-40 cards, weighted.
    - Keep "author reports a fix" as a column, captioned "authors rarely report back".
12. **Tool funnel:** labels collide into an unreadable mass.
    - Label only the 12 points furthest outside the funnel, plus the 5 most-named tools.
    - Everything else goes to hover.
13. **Bundles (`bundles.js`):**
    - The edge-bundled circle is a hairball. Draw only edges inside bundles by default, and all edges of a card on hover or tap.
    - Hide bundles with `persistence < 0.5` behind a "show fragile bundles" toggle.
14. **Profile (`profile.js`):**
    - Format p-values to 2 decimals.
    - The summary says "rising" only when `p_adj < 0.05`, otherwise "no clear change".
    - Format every percent to 1 decimal.
15. **Receipt (`receipt.js`):**
    - Format money to 2 decimals ("$22.51 total").
    - Slope-bar labels overlap. Merge phases under 2% of both calls and cost into "other".
16. **Quality (`quality.js`):**
    - Show the planted recovery from `method.quality.planted_recovery` (S8b makes it non-null).
    - Label wording runs "original wording", "rewording 1", and "rewording 2".
17. **Concentration (`concentration.js`):**
    - Color by `concentration.flagged`: true is the accent, false is muted, null is hollow grey.
    - Add both axis labels.
18. **Mobile:** run `scripts/essay-check.sh` at 375 px. Extend it to assert that no two text labels inside one chart overlap (measure SVG text bounding boxes).

- [ ] Fix each item. Add or extend node tests for every `prepare()` change.
- [ ] `node --test essay/test` passes, `scripts/essay-check.sh` passes, and `scripts/verify.sh` prints `verify: ok`.
- [ ] Commit after every 3 to 4 items, push, and open the PR. Final message: PR URL, the node test summary, and the essay-check result.

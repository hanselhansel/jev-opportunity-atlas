// S8a real-data polish: one test per finding. Prepare-level assertions only;
// the DOM-level items are covered by scripts/essay-check.sh.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(
  readFileSync(new URL("../fixtures/story.fixture.json", import.meta.url)),
);

const { titleOf } = await import("../lib/md.js");
const { labelFor, titleCase } = await import("../lib/labels.js");
const funnel = await import("../charts/funnel-units.js");
const voronoi = await import("../charts/voronoi-needs.js");
const forest = await import("../charts/forest-top.js");
const terms = await import("../charts/terms-columns.js");
const mekko = await import("../charts/role-mekko.js");
const stripes = await import("../charts/need-stripes.js");
const radar = await import("../charts/cost-radar.js");
const builders = await import("../charts/builders-scatter.js");
const closedOpen = await import("../charts/closed-open.js");
const toolFunnel = await import("../charts/tool-funnel.js");
const bundles = await import("../charts/bundles.js");
const profile = await import("../charts/profile.js");
const receipt = await import("../charts/receipt.js");
const quality = await import("../charts/quality.js");
const concentration = await import("../charts/concentration.js");

// 1. title and H1 come from the markdown, never hard-coded
test("titleOf reads the first # heading of story.md", () => {
  const md = readFileSync(
    new URL("../content/story.fixture.md", import.meta.url),
    "utf8",
  );
  assert.equal(titleOf(md), "Startup opportunities in a year of Hacker News");
  assert.equal(titleOf("no heading\njust a paragraph"), null);
});

// 2. funnel step markers + zoom stage
test("funnel marks counted, sampled and estimated steps", () => {
  const d = funnel.prepare(fixture);
  const marker = Object.fromEntries(d.steps.map((s) => [s.key, s.marker]));
  assert.equal(marker.all, "counted");
  assert.equal(marker.eligible, "counted");
  assert.match(marker.screened, /Jev read this sample/);
  assert.match(marker.firsthand, /estimated for all eligible/);
  assert.match(marker.placed, /estimated for all eligible/);
});

test("funnel zoom stage rescales to 1 dot = 100 at the sample step", () => {
  const d = funnel.prepare(fixture);
  const zoom = d.stages.find((s) => s.unit === 100);
  assert.ok(zoom, "no zoomed stage");
  const firsthand = fixture.funnel.steps.find((s) => s.key === "firsthand").count;
  assert.equal(zoom.dots, Math.round(firsthand / 100));
});

// 3. voronoi prepare: unplaced is a sector of the same circle
test("voronoi tree nests unplaced inside the same root", () => {
  const d = voronoi.prepare(fixture);
  const top = d.tree.children.map((c) => c.id);
  assert.ok(top.includes("__unplaced"));
  const total = d.tree.children.reduce((a, c) => a + c.value, 0);
  assert.ok(Math.abs(total - 1) < 0.02, `children sum to ${total}`);
});

// 4. forest counts collapse under 700px
test("forest counts column shows problems/authors when narrow", () => {
  const { rows } = forest.prepare(fixture);
  const wide = forest.countsLine(rows[0], false);
  const narrow = forest.countsLine(rows[0], true);
  assert.match(wide, /threads/);
  assert.doesNotMatch(narrow, /threads/);
  assert.match(narrow, /problems.*authors/);
});

// 5. terms headers wrap to 2 short lines, picker when narrow
test("terms group labels wrap over at most 2 short lines", () => {
  const { groups } = terms.prepare(fixture);
  for (const g of groups) {
    assert.ok(g.labelLines.length <= 2, g.id);
    assert.ok(g.labelLines.every((l) => l.length <= 10), g.labelLines);
  }
});

test("terms switches to a group picker under 480px", () => {
  assert.equal(terms.prepare(fixture, 375).picker, true);
  assert.equal(terms.prepare(fixture, 700).picker, false);
});

// 6+7. role mekko: top 6 roles get palette colors, rest grey, human labels
test("mekko assigns palette colors to the top 6 roles only", () => {
  const { roles } = mekko.prepare(fixture);
  assert.ok(roles.length <= 7);
  assert.equal(roles.at(-1).id, "other");
  roles.slice(0, -1).forEach((r, i) => assert.equal(r.colorIndex, i));
  assert.equal(roles.at(-1).colorIndex, null);
});

test("mekko legend uses human labels from story.labels", () => {
  const { roles } = mekko.prepare(fixture);
  const ds = roles.find((r) => r.id === "data_scientist");
  assert.ok(ds, "data_scientist not in top roles");
  assert.equal(ds.label, "Data scientist");
});

test("labelFor maps ids through story.labels with title-case fallback", () => {
  const s = { labels: { domains: { consumer_tech: "Consumer tech" } } };
  assert.equal(labelFor(s, "domains", "consumer_tech"), "Consumer tech");
  assert.equal(labelFor(s, "domains", "social_media"), "Social Media");
  assert.equal(labelFor(s, "roles", "data_scientist"), "Data Scientist");
  assert.equal(titleCase("devtools"), "Devtools");
});

// 8. need stripes: log(quarter share / full-year share), both signs
test("stripes color is log(quarter share / full-year share)", () => {
  const mk = (v) => ({ est: v, lo50: v, hi50: v, lo95: v, hi95: v, n: 100, sparse: false });
  const g = {
    id: "g01", short: "g", label: "G", share: mk(0.1), change: { est: 0 },
    quarters: { Q1: mk(0.15), Q2: mk(0.1), Q3: mk(0.05), Q4: mk(0.1) },
  };
  const { rows } = stripes.prepare({ groups: [g] });
  assert.ok(rows[0].cells[0].logRatio > 0, "hot quarter must be positive");
  assert.ok(Math.abs(rows[0].cells[1].logRatio) < 1e-9);
  assert.ok(rows[0].cells[2].logRatio < 0, "cool quarter must be negative");
});

test("stripes fixture has cells above and below the yearly share", () => {
  const { rows, maxAbs } = stripes.prepare(fixture);
  const signs = new Set(rows.flatMap((r) => r.cells.map((c) => Math.sign(c.logRatio))));
  assert.ok(signs.has(1) && signs.has(-1), "fixture must exercise both sides");
  assert.ok(maxAbs > 0);
});

// 9. cost radar: shared radius = largest group rate rounded up to 10%
test("radar radius max is the largest group rate rounded up to 10%", () => {
  const { rMax, panels } = radar.prepare(fixture);
  assert.ok(Number.isFinite(rMax));
  assert.ok(Math.abs(rMax * 10 - Math.round(rMax * 10)) < 1e-9, "rMax a multiple of 0.1");
  const maxEst = Math.max(
    ...panels.flatMap((p) => ["money", "time", "reliability", "customers"].map((a) => p.vals[a].est)),
  );
  assert.ok(rMax >= maxEst && rMax < maxEst + 0.1, `rMax ${rMax} vs max ${maxEst}`);
});

// 10. builders: label the 8 most underbuilt cards with >= 100 problems
test("builders labels the 8 lowest-ratio cards among n >= 100", () => {
  const { labeled } = builders.prepare(fixture);
  assert.equal(labeled.length, 8);
  assert.ok(labeled.every((l) => l.n_problems >= 100));
  const ratios = labeled.map((l) => l.ratio);
  assert.deepEqual(ratios, [...ratios].sort((a, b) => a - b));
});

// 11. closed-open opener: fix / no fix / not checked over top-40, weighted
test("closed-open waffle splits checked vs not checked, weighted", () => {
  const { waffle } = closedOpen.prepare(fixture);
  const sum = waffle.fix + waffle.nofix + waffle.unchecked;
  assert.ok(Math.abs(sum - 1) < 1e-6, `waffle sums to ${sum}`);
  assert.ok(waffle.unchecked > 0.4, "110 unmeasured cards should dominate");
  assert.ok(waffle.nofix > waffle.fix, "most checked problems have no reported fix");
});

// 12. tool funnel: 12 furthest outside + 5 most-named
test("tool funnel labels only the far outliers and most-named tools", () => {
  const { rows } = toolFunnel.prepare(fixture);
  const labeled = rows.filter((r) => r.labeled);
  const top5 = new Set([...rows].sort((a, b) => b.threads - a.threads).slice(0, 5).map((r) => r.name));
  for (const r of labeled) assert.ok(r.outside || top5.has(r.name), `${r.name} labeled without cause`);
  assert.ok(labeled.filter((r) => r.outside).length <= 12);
  for (const r of rows) if (top5.has(r.name)) assert.ok(r.labeled);
});

// 13. bundles: inside-bundle edges only, fragile flag at persistence < 0.5
test("bundles prepare keeps only edges inside one bundle by default", () => {
  const { insideEdges, bundles: bs } = bundles.prepare(fixture);
  const bundleOf = new Map();
  for (const b of bs) for (const c of b.cards) bundleOf.set(c, b.id);
  for (const e of insideEdges) {
    assert.ok(bundleOf.has(e.a) && bundleOf.get(e.a) === bundleOf.get(e.b));
  }
});

test("bundles flags persistence < 0.5 as fragile", () => {
  const fake = {
    cards: [{ id: "a", short: "a" }, { id: "b", short: "b" }],
    bundles: [{ id: "b1", cards: ["a", "b"], persistence: 0.3, share: null, groups_spanned: 1 }],
    edges: [{ a: "a", b: "b", score: 0.9 }],
  };
  const { bundles: bs } = bundles.prepare(fake);
  assert.equal(bs[0].fragile, true);
});

// 14. profile: p to 2 decimals, rising only when p_adj < 0.05, percents 1 decimal
test("profile summary gates rising on p_adj < 0.05", () => {
  const s = JSON.parse(JSON.stringify(fixture));
  const c = s.cards[0];
  c.change = { est: 0.01, lo95: 0, hi95: 0.02, p_adj: 0.3 };
  let p = profile.prepare(s, c.id);
  assert.match(p.summary, /no clear change/);
  assert.doesNotMatch(p.summary, /rising|cooling/);
  c.change = { est: 0.01, lo95: 0, hi95: 0.02, p_adj: 0.023456 };
  p = profile.prepare(s, c.id);
  assert.match(p.summary, /rising \(q 0\.02\)/);
});

test("profile formats percents to 1 decimal", () => {
  const s = JSON.parse(JSON.stringify(fixture));
  const c = s.cards[0];
  c.share.est = 0.01444;
  c.coping.paid.est = 0.555;
  const p = profile.prepare(s, c.id);
  assert.match(p.summary, /1\.4% of problems/);
  assert.match(p.summary, /55\.5% paid/);
});

// 15. receipt: money 2 decimals, phases < 2% of calls and cost merge into other
test("receipt merges tiny phases into other", () => {
  const { phases } = receipt.prepare(fixture);
  const other = phases.find((p) => p.phase === "other");
  assert.ok(other, "expected a merged other phase");
  for (const p of phases) {
    if (p.phase === "other") continue;
    assert.ok(p.shareCalls >= 0.02 || p.shareCost >= 0.02, p.phase);
  }
  const runsUsd = fixture.method.runs.reduce((a, r) => a + r.usd, 0);
  const sumUsd = phases.reduce((a, p) => a + p.usd, 0);
  assert.ok(Math.abs(sumUsd - runsUsd) < 0.01, "merge must conserve run spend");
});

test("receipt formats money to 2 decimals", () => {
  const { totalUsdText } = receipt.prepare(fixture);
  assert.match(totalUsdText, /^\$\d+\.\d{2}$/);
});

// 16. quality: wording labels and planted recovery
test("quality labels wording runs as original plus rewordings", () => {
  const { wording } = quality.prepare(fixture);
  assert.deepEqual(
    wording.screen.map((w) => w.label),
    ["original wording", "rewording 1", "rewording 2"],
  );
});

test("quality keeps the planted recovery array", () => {
  const { arrays } = quality.prepare(fixture);
  const planted = arrays.find((a) => a.key === "planted_recovery");
  assert.ok(planted);
  assert.equal(planted.value, fixture.method.quality.planted_recovery);
});

// 17. concentration: flagged passes through as true / false / null
test("concentration exposes the flagged field verbatim", () => {
  const { threads } = concentration.prepare(fixture);
  const flags = new Set(threads.map((t) => t.flagged));
  assert.ok(flags.has(true) && flags.has(false) && flags.has(null));
});

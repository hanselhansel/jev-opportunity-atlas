// S8d real-data review fixes: one test per finding. Prepare-level assertions;
// DOM geometry is covered by scripts/essay-check.sh.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(
  readFileSync(new URL("../fixtures/story.fixture.json", import.meta.url)),
);

const funnel = await import("../charts/funnel-units.js");
const closedOpen = await import("../charts/closed-open.js");
const stripes = await import("../charts/need-stripes.js");
const profile = await import("../charts/profile.js");
const coping = await import("../charts/coping-triangle.js");
const mekko = await import("../charts/role-mekko.js");
const terms = await import("../charts/terms-columns.js");

const stepCount = (k) => fixture.funnel.steps.find((s) => s.key === k).count;

// 1. funnel: each step's kept percent uses the right denominator
test("funnel step percents use per-step denominators", () => {
  const d = funnel.prepare(fixture);
  const at = (k) => d.steps.find((s) => s.key === k);
  const firsthandPct = ((stepCount("firsthand") / stepCount("eligible")) * 100).toFixed(1);
  const placedPct = Math.round((stepCount("placed") / stepCount("firsthand")) * 100);
  const screenedPct = Math.round((stepCount("screened") / stepCount("eligible")) * 100);
  assert.equal(at("firsthand").shareText, `${firsthandPct}% of eligible comments`);
  assert.equal(at("placed").shareText, `${placedPct}% of firsthand problems`);
  assert.equal(at("screened").shareText, `sample: ${screenedPct}% of eligible`);
  assert.equal(at("eligible").shareText, `${Math.round((stepCount("eligible") / stepCount("all")) * 100)}% kept`);
  assert.equal(at("all").shareText, null);
});

// 2. closed-open opener: weighted mean over checked cards only, two buckets
test("closed-open opener is the share-weighted fix rate over checked cards", () => {
  const { waffle } = closedOpen.prepare(fixture);
  const meas = fixture.cards.filter((c) => c.unsolved?.unsolved);
  const wsum = meas.reduce((a, c) => a + c.share.est, 0);
  const nofix = meas.reduce((a, c) => a + c.share.est * c.unsolved.unsolved.est, 0) / wsum;
  assert.ok(Math.abs(waffle.nofix - nofix) < 1e-9, `nofix ${waffle.nofix} vs ${nofix}`);
  assert.ok(Math.abs(waffle.fix - (1 - nofix)) < 1e-9);
  assert.equal(waffle.unchecked, undefined, "the opener drops the not-checked bucket");
});

// 3. need stripes: literal colors, cool side a visible blue on both themes
const hexLum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a, b) => {
  const [hi, lo] = [hexLum(a), hexLum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

test("stripes returns distinct fills for below/flat/above the yearly share", () => {
  const mk = (v) => ({ est: v, lo50: v, hi50: v, lo95: v, hi95: v, n: 100, sparse: false });
  const share = 0.5;
  const g = {
    id: "g01", short: "g", label: "G", share: mk(share), change: { est: 0 },
    quarters: {
      Q1: mk(share * Math.exp(0.3)),
      Q2: mk(share),
      Q3: mk(share * Math.exp(-0.3)),
      Q4: mk(share),
    },
  };
  const { rows, maxAbs } = stripes.prepare({ groups: [g] });
  assert.ok(Math.abs(maxAbs - 0.3) < 1e-9);
  const [hot, flat, cool] = [rows[0].cells[0].fill, rows[0].cells[1].fill, rows[0].cells[2].fill];
  assert.ok(/^#[0-9a-f]{6}$/i.test(cool), `cool fill must be a literal color, got ${cool}`);
  assert.notEqual(cool, flat);
  assert.notEqual(hot, flat);
  assert.notEqual(cool, hot);
  for (const paper of ["#fbfaf7", "#17191c"]) {
    assert.ok(contrast(cool, paper) >= 3, `cool ${cool} vs ${paper}: ${contrast(cool, paper).toFixed(2)}`);
  }
});

// 4. profile: quality labels renamed, group is a separate muted chip
test("profile labels severe3/specific3 by meaning, not scale", () => {
  const p = profile.prepare(fixture, fixture.cards[0].id);
  const who = p.sections.find((s) => s.title === "Who");
  const labels = who.lines.map((l) => l.label);
  assert.ok(labels.includes("real cost or worse"), labels.join(","));
  assert.ok(labels.includes("very specific"), labels.join(","));
  assert.ok(!labels.some((l) => /of 3/.test(l)), labels.join(","));
});

test("profile renders the group as its own muted chip line", () => {
  const card = fixture.cards[0];
  const fmt = { pct: (v, d = 1) => (v * 100).toFixed(d) + "%", n: (v) => String(v) };
  const html = profile.sheetHtml(card, fixture, fmt);
  const group = fixture.groups.find((g) => g.id === card.group).label;
  assert.match(html, /class="gchip"/);
  assert.ok(html.includes(`<span class="gchip">${group}</span>`), "group chip line");
  assert.ok(!html.includes(`${card.statement} ${group}.`), "statement and group must not run together");
});

// 5. coping triangle: side list is the commercial (pay, switch or quit) ranking
test("coping side list sorts by commercial rate", () => {
  const { side, sideTitle } = coping.prepare(fixture);
  assert.equal(sideTitle, "Pay, switch, or quit");
  const rates = side.map((c) => c.commercial);
  assert.deepEqual(rates, [...rates].sort((a, b) => b - a));
  const top2 = fixture.cards
    .map((c) => ({ id: c.id, v: c.coping?.commercial?.est ?? -1 }))
    .sort((a, b) => b.v - a.v)
    .slice(0, 2)
    .map((c) => c.id);
  assert.deepEqual(side.slice(0, 2).map((c) => c.id), top2);
});

// 6. role mekko: only columns wider than 80px get a printed label
test("mekko labels only columns wider than 80px", () => {
  const { columns } = mekko.prepare(fixture);
  for (const c of columns) {
    assert.equal(c.labeled, c.px > 80, `${c.id} px=${c.px.toFixed(1)} labeled=${c.labeled}`);
  }
  assert.ok(columns.some((c) => c.labeled), "at least one column is labeled");
  assert.ok(columns.some((c) => !c.labeled), "fixture should exercise unlabeled columns");
});

// 7. terms columns: never truncate, rows of <=5 (desktop) or 2 (phone)
test("terms never truncates a word", () => {
  for (const w of [700, 375]) {
    const d = terms.prepare(fixture, w);
    for (const g of d.groups) {
      const full = (fixture.terms[g.id] || []).slice(0, 8).map((t) => t.term);
      assert.deepEqual(g.terms.map((t) => t.term), full, `${g.id} at ${w}px`);
      for (const t of g.terms) assert.equal(t.label, t.term, "rendered label is the full term");
    }
  }
});

test("terms lays out rows of at most 5 columns on desktop, 2 on phones", () => {
  const d = terms.prepare(fixture, 700);
  assert.ok(d.cols <= 5 && d.cols >= 1);
  assert.ok(d.rows.every((r) => r.length <= 5));
  assert.equal(d.rows.length, Math.ceil(13 / d.cols));
  const m = terms.prepare(fixture, 375);
  assert.equal(m.cols, 2);
  assert.equal(m.rows.length, 7);
});

test("terms columns stay wide enough for the longest term", () => {
  const mk = (term) => ({
    groups: [{ id: "g01", short: "g", label: "G" }],
    terms: { g01: [{ term, z: 2, lo95: 1, hi95: 3, n_comments: 40, n_authors: 20 }] },
  });
  for (const w of [700, 500, 375]) {
    const d = terms.prepare(mk("averylongdistinctiveterm"), w);
    assert.ok(d.colW >= d.needW, `width ${w}: colW ${d.colW} < needW ${d.needW}`);
  }
});

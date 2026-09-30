import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { prepare, rank } from "../charts/opportunity.js";

const story = JSON.parse(
  readFileSync(fileURLToPath(new URL("../fixtures/story.fixture.json", import.meta.url))),
);

test("all-zero weights fall back to equal weights and set a notice flag", () => {
  const zero = Object.fromEntries(Object.keys(story.score_presets.balanced).map((k) => [k, 0]));
  const out = prepare(story, zero);
  assert.equal(out.notice, true);
  const used = out.weights;
  const vals = Object.values(used);
  assert.ok(vals.every((v) => v === vals[0] && v > 0), "expected equal positive weights");
});

test("preset weights produce a ranked list of at most 20 rows", () => {
  const out = prepare(story, story.score_presets.balanced);
  assert.equal(out.notice, false);
  assert.ok(out.rows.length > 0 && out.rows.length <= 20);
  const scores = out.rows.map((r) => r.score);
  assert.deepEqual([...scores].sort((a, b) => b - a), scores, "rows not sorted by score");
});

test("unsolved weight above zero restricts ranking to measured cards", () => {
  const w = { share: 0, change: 0, paid: 0, unsolved: 1, severity3: 0, launch_ratio: 0, reliability: 0, customers: 0 };
  const out = prepare(story, w);
  assert.equal(out.restricted, true);
  assert.ok(out.rows.every((r) => r.hasUnsolved));
});

test("the first five rows are one tied group with no numeric labels", () => {
  const out = prepare(story, story.score_presets.balanced);
  const first = out.rows.slice(0, 5);
  assert.equal(first.length, 5);
  for (const r of first) {
    assert.equal(r.tied, true);
    assert.equal(r.rankLabel ?? null, null);
  }
  const scores = first.map((r) => r.score);
  assert.deepEqual(
    [...scores].sort((a, b) => b - a),
    scores,
    "score order must hold inside the tied group",
  );
});

test("rows six onward keep numeric ranks starting at 6", () => {
  const out = prepare(story, story.score_presets.balanced);
  assert.ok(out.rows.length >= 6);
  const sixth = out.rows[5];
  assert.equal(sixth.tied, false);
  assert.equal(sixth.rank, 6);
  assert.equal(sixth.rankLabel, 6);
});

test("unstable flag: |rank_quantiles median - displayed rank| > 5", () => {
  const out = prepare(story, story.score_presets.balanced);
  for (const r of out.rows) {
    const qs = r.quantiles || [];
    const med = [...qs].sort((a, b) => a - b)[Math.floor(qs.length / 2)] || 0;
    const expect = qs.length > 0 && Math.abs(med - r.rank) > 5;
    assert.equal(Boolean(r.unstable), expect, `${r.id}: med ${med} vs rank ${r.rank}`);
  }
});

test("rank is deterministic and contribution bars sum to the score", () => {
  const out = prepare(story, story.score_presets.growth);
  for (const r of out.rows.slice(0, 5)) {
    const sum = Object.values(r.contrib).reduce((a, b) => a + b, 0);
    assert.ok(Math.abs(sum - r.score) < 1e-9);
  }
  assert.equal(typeof rank, "function");
});

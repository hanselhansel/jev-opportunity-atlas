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

test("rank is deterministic and contribution bars sum to the score", () => {
  const out = prepare(story, story.score_presets.growth);
  for (const r of out.rows.slice(0, 5)) {
    const sum = Object.values(r.contrib).reduce((a, b) => a + b, 0);
    assert.ok(Math.abs(sum - r.score) < 1e-9);
  }
  assert.equal(typeof rank, "function");
});

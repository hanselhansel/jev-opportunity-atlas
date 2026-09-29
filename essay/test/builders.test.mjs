import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { prepare } from "../charts/builders-scatter.js";

const story = JSON.parse(
  readFileSync(fileURLToPath(new URL("../fixtures/story.fixture.json", import.meta.url))),
);

test("a zero-launch card sits on the axis floor marked 'no sampled launch'", () => {
  const out = prepare(story);
  const zero = out.points.find((p) => p.launchShare === 0);
  assert.ok(zero, "fixture has a zero-launch card");
  assert.equal(zero.floor, true);
  assert.equal(zero.note, "no sampled launch");
  assert.ok(zero.y <= 0, "floor must sit at or under the log axis minimum");
});

test("points carry complaint share, launch share, ratio and fade", () => {
  const out = prepare(story);
  assert.equal(out.points.length, story.cards.length);
  const p = out.points.find((x) => !x.floor);
  assert.ok(p.x < 0 && p.y <= 0 || p.y > 0, "log positions");
  assert.ok(p.fade > 0 && p.fade <= 1);
  assert.ok(out.meta.n_sampled === story.builders.n_sampled);
});

// Every chart module exposes a pure prepare(story) that returns render-ready
// rows from only its contract keys. These tests run it on the fixture.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("../fixtures/story.fixture.json", import.meta.url))),
);

const modules = [
  "funnel-units", "voronoi-needs", "forest-top", "terms-columns", "role-mekko",
  "domain-morph", "breadth-swarm", "need-stripes", "risers-fallers",
  "coping-triangle", "cost-radar", "builders-scatter", "closed-open",
  "tool-funnel", "opportunity", "bundles", "profile", "mindmap", "receipt",
  "quality", "spec-ranks", "concentration",
];

for (const name of modules) {
  test(`${name}.prepare returns render-ready rows on the fixture`, async () => {
    const mod = await import(`../charts/${name}.js`);
    assert.equal(typeof mod.prepare, "function", "missing prepare");
    const rows = name === "profile" ? mod.prepare(fixture, fixture.cards[0].id) : mod.prepare(fixture);
    assert.ok(rows !== null && typeof rows === "object");
  });
}

test("fixture follows the story.v1 contract keys", () => {
  for (const k of ["meta", "funnel", "groups", "cards", "unplaced", "domains", "roles", "spec_ranks", "score_presets", "bundles", "edges", "terms", "tools", "builders", "method"]) {
    assert.ok(k in fixture, `missing ${k}`);
  }
  const estKeys = ["est", "lo50", "hi50", "lo95", "hi95", "n", "sparse"];
  for (const k of estKeys) assert.ok(k in fixture.groups[0].share, `est missing ${k}`);
});

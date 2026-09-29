import test from "node:test";
import assert from "node:assert/strict";
import { extents, fade, tooFew } from "../lib/glyph.js";

const scale = (v) => v * 100; // 1 unit -> 100 px

test("extents maps an Est to dot, 50% core and 95% bar", () => {
  const est = { est: 0.10, lo50: 0.09, hi50: 0.11, lo95: 0.07, hi95: 0.13, n: 500, sparse: false };
  const g = extents(est, scale);
  const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
  close(g.cx, 10);
  close(g.x50a, 9);
  close(g.x50b, 11);
  close(g.x95a, 7);
  close(g.x95b, 13);
  assert.equal(g.sparse, false);
});

test("fade uses the relative 95% half-width: full, 60%, 30%", () => {
  // half-width / est < 0.25 -> 1
  assert.equal(fade({ est: 0.10, lo95: 0.09, hi95: 0.11 }), 1);
  // 0.25-0.5 -> 0.6
  assert.equal(fade({ est: 0.10, lo95: 0.07, hi95: 0.13 }), 0.6);
  // > 0.5 -> 0.3
  assert.equal(fade({ est: 0.10, lo95: 0.04, hi95: 0.16 }), 0.3);
});

test("sparse estimates fade and flag too few", () => {
  const est = { est: 0.02, lo50: 0, hi50: 0.04, lo95: 0, hi95: 0.06, n: 12, sparse: true };
  assert.equal(fade(est), 0.3);
  assert.equal(tooFew(est), true);
  assert.equal(tooFew(null), true);
  assert.equal(tooFew({ est: 0.1, lo95: 0.09, hi95: 0.11, n: 500, sparse: false }), false);
});

test("null estimate returns no extents", () => {
  assert.equal(extents(null, scale), null);
});

// The shared interval glyph and certainty fade.
// dot = estimate, thick core = 50% interval, thin bar = 95% interval.
// Certainty fade: relative 95% half-width under 25% -> full, 25-50% -> 0.6,
// over 50% -> 0.3. Sparse or missing estimates read as "too few".

export function fade(est) {
  if (!est || est.sparse) return 0.3;
  const half = (est.hi95 - est.lo95) / 2;
  const rel = est.est > 0 ? half / est.est : Infinity;
  if (rel < 0.25) return 1;
  if (rel <= 0.5) return 0.6;
  return 0.3;
}

export function tooFew(est) {
  return !est || est.sparse === true;
}

export function extents(est, scale) {
  if (!est) return null;
  return {
    cx: scale(est.est),
    x50a: scale(est.lo50),
    x50b: scale(est.hi50),
    x95a: scale(est.lo95),
    x95b: scale(est.hi95),
    opacity: fade(est),
    sparse: est.sparse === true,
  };
}

// Draws the glyph into any d3-ish selection (g element). y is the row center.
export function drawGlyph(sel, est, scale, y = 0, cls = "") {
  const g = extents(est, scale);
  if (!g) {
    sel
      .append("text")
      .attr("class", `too-few ${cls}`)
      .attr("x", scale(0))
      .attr("y", y + 4)
      .text("too few");
    return;
  }
  const row = sel
    .append("g")
    .attr("class", `glyph ${cls}`)
    .attr("opacity", g.opacity)
    .classed("sparse", g.sparse);
  row
    .append("line")
    .attr("class", "bar95")
    .attr("x1", g.x95a)
    .attr("x2", g.x95b)
    .attr("y1", y)
    .attr("y2", y);
  row
    .append("line")
    .attr("class", "bar50")
    .attr("x1", g.x50a)
    .attr("x2", g.x50b)
    .attr("y1", y)
    .attr("y2", y);
  row.append("circle").attr("class", "dot").attr("cx", g.cx).attr("cy", y).attr("r", 3);
}

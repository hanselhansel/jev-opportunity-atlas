// Risers and fallers: cards with BH q < 0.05 on H2 - H1. Shrunk dot plus
// raw tick on a shared zero-centered axis.
import { tooFew } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const rows = story.cards
    .filter((c) => c.change && c.change.p_adj < 0.05)
    .map((c) => ({
      id: c.id,
      label: c.short,
      group: c.group,
      shrunk: c.change.shrunk ?? c.change.est,
      raw: c.change.est,
      lo95: c.change.lo95,
      hi95: c.change.hi95,
      h1: c.h1.est,
      h2: c.h2.est,
      q: c.change.p_adj,
      hollow: (c.concentration?.top3_threads ?? 0) > 0.5,
      sparse: tooFew(c.share),
    }))
    .sort((a, b) => b.shrunk - a.shrunk);
  return { rows };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { rows } = prepare(story);
  el.innerHTML = "";
  const rowH = 21, labelW = 150, W = 700, H = Math.max(80, rows.length * rowH + 34);
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const bound = d3.max(rows, (r) => Math.max(Math.abs(r.lo95), Math.abs(r.hi95), Math.abs(r.raw))) * 1.15 || 0.01;
  const x = d3.scaleLinear().domain([-bound, bound]).range([0, W - labelW - 20]);

  const gx = labelW;
  svg.append("line").attr("x1", gx + x(0)).attr("x2", gx + x(0)).attr("y1", 4).attr("y2", H - 26).attr("stroke", "var(--line)");

  const row = svg
    .selectAll("g.r")
    .data(rows)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${i * rowH + 14})`)
    .attr("data-card", (d) => d.id)
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id));

  row.append("rect").attr("class", "hit").attr("x", 0).attr("y", -9).attr("width", W).attr("height", rowH - 2);
  row.append("text").attr("class", "row-label").attr("x", 0).attr("y", 4).text((d) => d.label).attr("fill", (d) => groupColor(d.group));
  row
    .append("line")
    .attr("x1", (d) => gx + x(d.lo95))
    .attr("x2", (d) => gx + x(d.hi95))
    .attr("stroke", "var(--muted)").attr("stroke-width", 1.5);
  row.append("line").attr("x1", (d) => gx + x(d.raw)).attr("x2", (d) => gx + x(d.raw)).attr("y1", -5).attr("y2", 5).attr("stroke", "var(--ink)").attr("stroke-width", 1);
  row
    .append("circle")
    .attr("cx", (d) => gx + x(d.shrunk))
    .attr("r", 3.4)
    .attr("fill", (d) => (d.hollow ? "none" : d.shrunk > 0 ? "var(--accent)" : "var(--h0)"))
    .attr("stroke", (d) => (d.shrunk > 0 ? "var(--accent)" : "var(--h0)"))
    .attr("stroke-width", 1.5);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "H2 minus H1 change in share (percentage points). Dot is shrunk; tick is raw; hollow = top-3 threads carry it.";
  el.appendChild(cap);
}

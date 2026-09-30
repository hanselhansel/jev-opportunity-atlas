// Need stripes: 13 groups x 4 quarters. Cell color = log(quarter / full-year),
// diverging scale, certainty fade. A notch marks top-thread-heavy cells.
import { fade } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const rows = story.groups
    .map((g) => {
      const cells = ["Q1", "Q2", "Q3", "Q4"].map((q) => {
        const est = g.quarters[q];
        // quarter share is normalized within its quarter; compare to the
        // full-year share so flat groups sit at log 0
        const logRatio = est ? Math.log(Math.max(1e-9, est.est) / Math.max(1e-9, g.share.est)) : 0;
        return { q: q, est, logRatio, fade: fade(est), sparse: est?.sparse === true };
      });
      return { id: g.id, label: g.short || g.label, change: g.change.est, cells };
    })
    .sort((a, b) => b.change - a.change);
  const maxAbs = Math.max(1e-6, ...rows.flatMap((r) => r.cells.map((c) => Math.abs(c.logRatio))));
  return { rows, maxAbs };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { rows, maxAbs } = prepare(story);
  el.innerHTML = "";
  const W = 700, rowH = 26, labelW = 110, cellW = (W - labelW - 20) / 4;
  const H = rows.length * rowH + 40;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const color = d3.scaleDiverging(["var(--h0)", "var(--paper)", "var(--accent)"]).domain([-maxAbs, 0, maxAbs]);

  const row = svg.selectAll("g.r").data(rows).join("g").attr("transform", (d, i) => `translate(0,${i * rowH + 16})`);
  row.append("text").attr("class", "row-label").attr("x", 0).attr("y", 15).text((d) => d.label).attr("fill", (d) => groupColor(d.id));
  row
    .selectAll("rect.c")
    .data((d) => d.cells)
    .join("rect")
    .attr("class", "c")
    .attr("x", (c, i) => labelW + i * cellW)
    .attr("y", 0)
    .attr("width", cellW - 3)
    .attr("height", rowH - 4)
    .attr("rx", 2)
    .attr("fill", (c) => color(c.logRatio))
    .attr("opacity", (c) => c.fade)
    .append("title")
    .text((c) => `${c.q}: ${api.fmt.pct(c.est?.est, 2)} of problems${c.sparse ? " (few rows)" : ""}`);

  ["Q1", "Q2", "Q3", "Q4"].forEach((q, i) => {
    svg.append("text").attr("class", "axis").attr("x", labelW + i * cellW + cellW / 2).attr("y", 10).attr("text-anchor", "middle").text(q);
  });
  svg.append("text").attr("class", "axis").attr("x", W - 10).attr("y", H - 8).attr("text-anchor", "end").text("cooler \u2190 \u2192 hotter vs yearly share");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Quarter share versus full-year share, log scale. Shares sum to 100%.";
  el.appendChild(cap);
}

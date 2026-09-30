// Forest plot of the top 30 cards with the interval glyph and counts columns.
// Counts are right-aligned inside the container; under 700px wide only
// "problems / authors" is shown so the column never clips.
import { drawGlyph, tooFew } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

export function prepare(story, topN = 30) {
  const sorted = [...story.cards].sort((a, b) => b.share.est - a.share.est);
  const cut = sorted[Math.min(topN, sorted.length) - 1].share.est;
  const rows = [];
  sorted.forEach((c, i) => {
    const reaches = c.share.hi95 >= cut;
    if (i < topN || reaches) {
      rows.push({
        id: c.id,
        label: c.short,
        group: c.group,
        share: c.share,
        n_problems: c.n_problems,
        n_authors: c.n_authors,
        n_threads: c.n_threads,
        sparse: tooFew(c.share),
        beyond: i >= topN,
      });
    }
  });
  return { rows, cut };
}

export function countsLine(d, narrow, fmt) {
  const f = fmt || { n: (x) => (x == null ? "n/a" : x.toLocaleString("en-US")) };
  return narrow
    ? `${f.n(d.n_problems)} problems / ${f.n(d.n_authors)} authors`
    : `${f.n(d.n_problems)} problems / ${f.n(d.n_authors)} authors / ${f.n(d.n_threads)} threads`;
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { rows } = prepare(story);
  el.innerHTML = "";
  const narrow = (el.clientWidth || 700) < 700;
  // the wide counts line runs ~210px at the tick-label size
  const rowH = 22, labelW = 150, countsW = narrow ? 150 : 220, W = 700, H = rows.length * rowH + 30;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const x = d3.scaleLinear().domain([0, d3.max(rows, (r) => r.share.hi95) * 1.05]).range([0, W - labelW - countsW - 20]);

  const row = svg
    .selectAll("g.r")
    .data(rows)
    .join("g")
    .attr("class", "r")
    .attr("data-card", (d) => d.id)
    .attr("transform", (d, i) => `translate(0,${i * rowH + 12})`)
    .attr("opacity", (d) => (d.beyond ? 0.45 : 1))
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id));

  row.append("rect").attr("class", "hit").attr("x", 0).attr("y", -rowH / 2).attr("width", W).attr("height", rowH);
  row
    .append("rect")
    .attr("x", 0).attr("y", -7).attr("width", 6).attr("height", 14)
    .attr("fill", (d) => groupColor(d.group));
  row.append("text").attr("class", "row-label").attr("x", 10).attr("y", 4).text((d) => d.label);
  row.each(function (d) {
    drawGlyph(d3.select(this).append("g").attr("transform", `translate(${labelW},0)`), d.share, x, 0);
  });
  row
    .append("text")
    .attr("class", "tick-label")
    .attr("x", W - 8)
    .attr("y", 4)
    .attr("text-anchor", "end")
    .text((d) => countsLine(d, narrow, api.fmt));

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Share of all firsthand problems. Cards near the cut may be overstated.";
  el.appendChild(cap);
}

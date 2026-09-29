// Rank range strip: union of top-20 cards across specification alternatives.
// Bar = best-to-worst rank, dot = main run, ticks = alternatives.
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const cardOf = Object.fromEntries(story.cards.map((c) => [c.id, c]));
  const rows = (story.spec_ranks || []).map((r) => {
    const alts = Object.entries(r.alt_ranks || {}).map(([key, rank]) => ({ key, rank }));
    const ranks = [r.main_rank, ...alts.map((a) => a.rank)];
    return {
      id: r.card,
      label: cardOf[r.card]?.short || r.card,
      group: cardOf[r.card]?.group,
      main: r.main_rank,
      best: Math.min(...ranks),
      worst: Math.max(...ranks),
      alts,
      fragile: false,
    };
  });
  rows.sort((a, b) => a.main - b.main);
  rows.sort((a, b) => (b.worst - b.best) - (a.worst - a.best)).slice(0, 3).forEach((r) => (r.fragile = true));
  rows.sort((a, b) => a.main - b.main);
  return { rows, altKeys: [...new Set(rows.flatMap((r) => r.alts.map((a) => a.key)))] };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { rows, altKeys } = prepare(story);
  el.innerHTML = "";
  const rowH = 20, labelW = 140, W = 700, H = rows.length * rowH + 40;
  const maxRank = d3.max(rows, (r) => r.worst) || 60;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const x = d3.scaleLinear().domain([0.5, maxRank + 1]).range([0, W - labelW - 30]);

  svg.append("text").attr("class", "axis").attr("x", labelW).attr("y", 12).text("rank 1");
  svg.append("text").attr("class", "axis").attr("x", labelW + x.range()[1]).attr("y", 12).attr("text-anchor", "end").text(`rank ${maxRank}`);

  const row = svg
    .selectAll("g.r")
    .data(rows)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${i * rowH + 24})`)
    .attr("data-card", (d) => d.id)
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id));
  row.append("rect").attr("class", "hit").attr("x", 0).attr("y", -8).attr("width", W).attr("height", rowH - 2);
  row.append("text").attr("class", "cell-label").attr("x", 0).attr("y", 4).text((d) => `${d.fragile ? "! " : ""}${d.label}`).attr("fill", (d) => groupColor(d.group));
  row.append("line").attr("x1", (d) => labelW + x(d.best)).attr("x2", (d) => labelW + x(d.worst)).attr("y1", 0).attr("y2", 0).attr("stroke", (d) => (d.fragile ? "var(--accent)" : "var(--line)")).attr("stroke-width", (d) => (d.fragile ? 5 : 4)).attr("stroke-linecap", "round");
  row.each(function (d) {
    const g = d3.select(this);
    d.alts.forEach((a) => {
      g.append("line").attr("x1", labelW + x(a.rank)).attr("x2", labelW + x(a.rank)).attr("y1", -4).attr("y2", 4).attr("stroke", "var(--muted)").attr("stroke-width", 1);
    });
    g.append("circle").attr("cx", labelW + x(d.main)).attr("r", 3).attr("fill", "var(--ink)");
  });

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Bar: best-to-worst rank under ${altKeys.length} alternatives. Dot: main run. ! = fragile.`;
  el.appendChild(cap);
}

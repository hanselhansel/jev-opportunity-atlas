// Closed or open: one 100-unit waffle opener, then aligned columns for the
// top-40 replies-checked cards. A = author reports a fix, B = no reply fixed it.
import { drawGlyph, tooFew } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const measured = story.cards.filter((c) => c.unsolved);
  const totN = measured.reduce((a, c) => a + (c.unsolved.author_solved?.n || 0), 0) || 1;
  const solved = measured.reduce((a, c) => a + c.unsolved.author_solved.est * (c.unsolved.author_solved.n || 0), 0) / totN;
  const rows = measured
    .map((c) => ({
      id: c.id,
      label: c.short,
      group: c.group,
      share: c.share.est,
      a: c.unsolved.author_solved,
      b: c.unsolved.unsolved,
      sparse: tooFew(c.unsolved.unsolved),
    }))
    .sort((a, b) => b.share - a.share);
  return { waffle: { solved, unresolved: 1 - solved }, rows, unmeasured: story.cards.length - measured.length };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { waffle, rows, unmeasured } = prepare(story);
  el.innerHTML = "";

  // waffle
  const w = d3.select(el).append("svg").attr("viewBox", "0 0 700 74");
  const cells = 100, cw = 14, gap = 1;
  const solvedCells = Math.round(waffle.solved * cells);
  for (let i = 0; i < cells; i++) {
    const col = i % 25, rowi = Math.floor(i / 25);
    w.append("rect")
      .attr("x", 10 + col * (cw + gap) * 1.6)
      .attr("y", 8 + rowi * (cw + gap))
      .attr("width", cw).attr("height", cw).attr("rx", 2)
      .attr("fill", i < solvedCells ? "var(--good)" : "var(--line)");
  }
  w.append("text").attr("class", "row-label").attr("x", 420).attr("y", 34)
    .text(`${api.fmt.pct(waffle.solved, 0)} of problems got a reported fix`);

  // aligned columns
  const rowH = 19, labelW = 140, colW = 200, W = 700, H = rows.length * rowH + 34;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const xA = d3.scaleLinear().domain([0, 1]).range([0, colW]);
  const xB = d3.scaleLinear().domain([0, 1]).range([0, colW]);
  const bX = labelW + colW + 30;

  svg.append("text").attr("class", "axis").attr("x", labelW).attr("y", 10).text("author reports a fix");
  svg.append("text").attr("class", "axis").attr("x", bX).attr("y", 10).text("no reply fixed it");

  const row = svg
    .selectAll("g.r")
    .data(rows)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${i * rowH + 20})`)
    .attr("data-card", (d) => d.id)
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id));
  row.append("rect").attr("class", "hit").attr("x", 0).attr("y", -8).attr("width", W).attr("height", rowH - 2);
  row.append("text").attr("class", "cell-label").attr("x", 0).attr("y", 4).text((d) => d.label).attr("fill", (d) => groupColor(d.group));
  row.each(function (d) {
    drawGlyph(d3.select(this).append("g").attr("transform", `translate(${labelW},0)`), d.a, xA, 0);
    drawGlyph(d3.select(this).append("g").attr("transform", `translate(${bX},0)`), d.b, xB, 0);
  });

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Top ${rows.length} cards with replies checked. Other ${unmeasured}: not measured.`;
  el.appendChild(cap);
}

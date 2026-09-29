// Distinctive terms: 13 compact columns, top 8 terms by z with 95% intervals.
import { groupColor } from "../lib/palette.js";

export function prepare(story, topN = 8) {
  const groups = story.groups.map((g) => ({
    id: g.id,
    label: g.short || g.label,
    terms: (story.terms?.[g.id] || []).slice(0, topN).map((t) => ({
      term: t.term,
      z: t.z,
      lo95: t.lo95,
      hi95: t.hi95,
      n_comments: t.n_comments,
      n_authors: t.n_authors,
    })),
  }));
  return { groups };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { groups } = prepare(story);
  el.innerHTML = "";
  const colW = 52, rowH = 17, W = 700, H = 8 * rowH + 34;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const zMax = d3.max(groups, (g) => d3.max(g.terms, (t) => t.hi95)) || 1;
  const x = d3.scaleLinear().domain([0, zMax]).range([0, colW - 14]);

  const col = svg
    .selectAll("g.col")
    .data(groups)
    .join("g")
    .attr("transform", (d, i) => `translate(${i * colW + 4},0)`);

  col
    .append("text")
    .attr("class", "cell-label")
    .attr("y", 10)
    .attr("transform", (d, i) => `rotate(-28 4 10)`)
    .attr("x", 0)
    .text((d) => d.label)
    .attr("fill", (d) => groupColor(d.id));

  const t = col
    .selectAll("g.t")
    .data((d) => d.terms)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${22 + i * rowH})`);

  t.append("line")
    .attr("x1", (d) => x(d.lo95))
    .attr("x2", (d) => x(d.hi95))
    .attr("stroke", "var(--muted)")
    .attr("stroke-width", 1);
  t.append("circle").attr("cx", (d) => x(d.z)).attr("r", 2.4).attr("fill", "var(--ink)");
  t.append("text")
    .attr("class", "cell-label")
    .attr("y", -3)
    .text((d) => d.term.length > 7 ? d.term.slice(0, 7) : d.term)
    .append("title")
    .text((d) => d.term);

  t.append("title").text((d) => `${d.term}: ${d.n_comments} comments, ${d.n_authors} authors`);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Top distinctive terms per group, z with 95% intervals. Only q < 0.05 terms shown.";
  el.appendChild(cap);
}

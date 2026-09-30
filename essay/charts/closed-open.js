// Closed or open: a 100-unit opener splits every 100 problems into "a reply
// named a fix", "no reply fixed it", and "not checked". Then aligned columns
// for the top-40 replies-checked cards: author reports a fix vs unresolved.
import { drawGlyph, tooFew } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const measured = story.cards.filter((c) => c.unsolved);
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

  // weighted over the measured (top-40) cards, normalized to all placed cards
  const placedShare = story.cards.reduce((a, c) => a + (c.share?.est ?? 0), 0) || 1;
  const fix = measured.reduce((a, c) => a + c.share.est * (c.unsolved.author_solved?.est ?? 0), 0);
  const nofix = measured.reduce((a, c) => a + c.share.est * (c.unsolved.unsolved?.est ?? 0), 0);
  const waffle = {
    fix: fix / placedShare,
    nofix: nofix / placedShare,
    unchecked: Math.max(0, 1 - (fix + nofix) / placedShare),
  };
  return { waffle, rows, unmeasured: story.cards.length - measured.length };
}

const WAF = [
  { key: "fix", label: "a reply named a fix", fill: "var(--good)" },
  { key: "nofix", label: "no reply fixed it", fill: "var(--accent)" },
  { key: "unchecked", label: "not checked", fill: "var(--line)" },
];

export function mount(el, story, api) {
  const d3 = api.d3;
  const { waffle, rows, unmeasured } = prepare(story);
  el.innerHTML = "";

  // 100-unit opener: 5 rows of 20 squares
  const w = d3.select(el).append("svg").attr("viewBox", "0 0 700 120");
  const cells = 100, cw = 11, gap = 2;
  const counts = [];
  let used = 0;
  WAF.forEach((cat, i) => {
    const n = i === WAF.length - 1 ? cells - used : Math.round(waffle[cat.key] * cells);
    counts.push({ ...cat, n });
    used += n;
  });
  let ci = 0;
  const bounds = counts.map((cat) => { const s = ci; ci += cat.n; return { ...cat, start: s, end: ci }; });
  for (let i = 0; i < cells; i++) {
    const col = i % 20, rowi = Math.floor(i / 20);
    const cat = bounds.find((b) => i >= b.start && i < b.end) || bounds[bounds.length - 1];
    w.append("rect")
      .attr("x", 8 + col * (cw + gap))
      .attr("y", 8 + rowi * (cw + gap))
      .attr("width", cw).attr("height", cw).attr("rx", 2)
      .attr("fill", cat.fill)
      .append("title").text(cat.label);
  }
  // legend with counts
  const leg = w.append("g").attr("transform", "translate(300,16)");
  bounds.forEach((b, i) => {
    const g = leg.append("g").attr("transform", `translate(0,${i * 26})`);
    g.append("rect").attr("width", 10).attr("height", 10).attr("y", -9).attr("rx", 2).attr("fill", b.fill);
    g.append("text").attr("class", "row-label").attr("x", 16).attr("y", 0).text(`${b.n} of 100: ${b.label}`);
  });

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
  cap.textContent = `Of every 100 problems, few get a reported fix; authors rarely report back. Top ${rows.length} cards with replies checked. Other ${unmeasured}: not measured.`;
  el.appendChild(cap);
}

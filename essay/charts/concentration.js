// Concentration funnel plots: top-3 thread share and top-3 author share
// against card size, with simulated-null whiskers. Dots use the pipeline's
// flagged flag: true = accent, false = muted, null = hollow grey (untested).
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const pt = (c, key, nulKey) => ({
    id: c.id,
    label: c.short,
    group: c.group,
    n: c.n_problems,
    y: c.concentration[key],
    lo: c.concentration[nulKey][0],
    hi: c.concentration[nulKey][1],
    flagged: c.concentration.flagged ?? null,
    riser: c.change?.p_adj < 0.05 && c.change?.est > 0,
  });
  const cards = story.cards.filter((c) => c.concentration);
  return {
    threads: cards.map((c) => pt(c, "top3_threads", "null_threads")),
    authors: cards.map((c) => pt(c, "top3_authors", "null_authors")),
  };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { threads, authors } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 300, pw = 320, m = { t: 30, b: 30 };
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const allN = [...threads, ...authors].map((d) => d.n);
  const mkx = (x0) => d3.scaleLog().domain([Math.max(2, d3.min(allN) * 0.7), d3.max(allN) * 1.3]).range([x0, x0 + pw - 30]);
  const mky = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
  const g1 = svg.append("g");
  const g2 = svg.append("g");
  drawPanel(d3, g1, threads, mkx(30), mky, "top 3 threads");
  drawPanel(d3, g2, authors, mkx(370), mky, "top 3 authors");

  // axis labels
  svg.append("text").attr("class", "axis").attr("x", 30 + pw / 2).attr("y", H - 6).attr("text-anchor", "middle").text("problems (log)");
  svg.append("text").attr("class", "axis").attr("x", 370 + pw / 2).attr("y", H - 6).attr("text-anchor", "middle").text("problems (log)");
  svg.append("text").attr("class", "axis").attr("x", 8).attr("y", (H - m.b + m.t) / 2).attr("text-anchor", "middle").attr("transform", `rotate(-90 8 ${(H - m.b + m.t) / 2})`).text("share from top 3");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Accent dots sit above their null range; grey dots unflagged; hollow dots untested.";
  el.appendChild(cap);
}

function drawPanel(d3, g, rows, x, y, title) {
  g.append("text").attr("class", "axis").attr("x", x.range()[0]).attr("y", 22).text(title);
  rows.forEach((d) => {
    const px = x(d.n), py = y(d.y);
    g.append("line").attr("x1", px).attr("x2", px).attr("y1", y(d.lo)).attr("y2", y(d.hi)).attr("stroke", "var(--grey)").attr("opacity", 0.3);
    const c = g.append("circle")
      .attr("data-card", d.id)
      .attr("cx", px).attr("cy", py)
      .attr("r", d.flagged ? 4 : 2.6)
      .attr("opacity", 0.8);
    if (d.flagged === null) {
      c.attr("fill", "none").attr("stroke", "var(--grey)").attr("stroke-width", 1.2);
    } else if (d.flagged) {
      c.attr("fill", "var(--accent)").attr("stroke", "none");
    } else {
      c.attr("fill", "var(--grey)").attr("stroke", "none");
    }
    c.append("title")
      .text(`${d.label}: ${(d.y * 100).toFixed(0)}% from top 3, n=${d.n}${d.flagged === null ? " (untested)" : d.flagged ? " (concentrated)" : ""}`);
  });
}

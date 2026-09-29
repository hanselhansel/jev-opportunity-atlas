// Domain bubbles settle into a complaint-rate lollipop. Rendered as one
// aligned view: talk share on the left, complaint rate as a lollipop.
import { drawGlyph, fade } from "../lib/glyph.js";

export function prepare(story) {
  const totTalk = story.domains.reduce((a, d) => a + d.discussion.est, 0);
  const totPain = story.domains.reduce((a, d) => a + d.complaints.est, 0);
  const overall = totPain / Math.max(1e-9, totTalk);
  const rows = story.domains
    .map((d) => ({
      id: d.id,
      discussion: d.discussion,
      complaints: d.complaints,
      rate: d.rate,
      ratio: d.rate.est / Math.max(1e-9, overall),
      fade: fade(d.rate),
    }))
    .sort((a, b) => b.rate.est - a.rate.est);
  return { rows, overall };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { rows, overall } = prepare(story);
  el.innerHTML = "";
  const rowH = 20, labelW = 110, bubbleW = 90, W = 700, H = rows.length * rowH + 34;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const maxRate = d3.max(rows, (r) => r.rate.hi95) * 1.1;
  const x = d3.scaleLog().domain([maxRate / 200, maxRate]).range([0, W - labelW - bubbleW - 60]);
  const r = d3.scaleSqrt().domain([0, d3.max(rows, (d) => d.discussion.est)]).range([1.5, 8]);

  const row = svg
    .selectAll("g.r")
    .data(rows)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${i * rowH + 14})`)
    .attr("opacity", (d) => d.fade);

  row.append("text").attr("class", "row-label").attr("x", 0).attr("y", 4).text((d) => d.id);
  row
    .append("circle")
    .attr("cx", labelW + 20)
    .attr("cy", 0)
    .attr("r", (d) => r(d.discussion.est))
    .attr("fill", (d) => (d.ratio > 1 ? "var(--accent)" : "var(--h0)"))
    .attr("opacity", 0.6)
    .append("title")
    .text((d) => `${api.fmt.pct(d.discussion.est)} of talk, ${api.fmt.pct(d.complaints.est)} of pain`);
  const gx = labelW + bubbleW;
  // reference line at overall rate
  svg
    .append("line")
    .attr("x1", gx + x(overall))
    .attr("x2", gx + x(overall))
    .attr("y1", 6)
    .attr("y2", H - 24)
    .attr("stroke", "var(--muted)")
    .attr("stroke-dasharray", "3 3");
  row.each(function (d) {
    drawGlyph(d3.select(this).append("g").attr("transform", `translate(${gx},0)`), d.rate, x, 0);
  });
  row
    .append("text")
    .attr("class", "tick-label")
    .attr("x", gx + x.range()[1] + 8)
    .attr("y", 4)
    .text((d) => `x${d.ratio.toFixed(1)}`);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Bubble: share of talk. Lollipop: pain per comment, log axis, line = overall rate.";
  el.appendChild(cap);
}

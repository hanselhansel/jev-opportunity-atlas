// Builders vs complainers: log-log complaint share vs sampled launch share,
// y = x diagonal, shaded underbuilt zone, floor rail for zero-launch cards.
import { fade } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

export function prepare(story) {
  const points = story.cards.map((c) => {
    const launch = c.builders?.launch_share?.est ?? null;
    const complaint = c.share?.est ?? 0;
    const zero = !launch || launch <= 0;
    return {
      id: c.id,
      label: c.short,
      group: c.group,
      complaintShare: complaint,
      launchShare: launch || 0,
      x: Math.log10(Math.max(complaint, 1e-5)),
      y: zero ? 0 : Math.log10(Math.max(launch, 1e-5)),
      floor: zero,
      note: zero ? "no sampled launch" : null,
      ratio: c.builders?.ratio?.est ?? null,
      fade: fade(c.builders?.ratio || c.share),
    };
  });
  return {
    points,
    meta: {
      n_sampled: story.builders?.n_sampled ?? 0,
      n_population: story.builders?.n_population ?? 0,
      match_rate: story.builders?.match_rate ?? null,
    },
  };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { points, meta } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 380, m = { l: 55, r: 20, t: 30, b: 40 };
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);

  const xs = points.map((p) => p.x);
  const ys = points.filter((p) => !p.floor).map((p) => p.y);
  const lo = Math.min(d3.min(xs), d3.min(ys) ?? -4);
  const hi = Math.max(d3.max(xs), d3.max(ys) ?? -2) + 0.1;
  const x = d3.scaleLinear().domain([lo, hi]).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([lo, hi]).range([H - m.b, m.t]);
  const floorY = y(lo) + 14; // rail under the axis

  // underbuilt zone: well below the diagonal
  svg
    .append("path")
    .attr("d", `M${x(lo)},${y(hi - 1)}L${x(hi)},${y(hi - 1 + (hi - lo))}L${x(hi)},${y(lo)}L${x(lo)},${y(lo)}Z`)
    .attr("fill", "var(--h3)")
    .attr("opacity", 0.07);
  // diagonal y = x
  svg.append("line").attr("x1", x(lo)).attr("y1", y(lo)).attr("x2", x(hi)).attr("y2", y(hi)).attr("stroke", "var(--muted)").attr("stroke-dasharray", "4 4");
  svg.append("text").attr("class", "axis").attr("x", x(hi) - 4).attr("y", y(hi) + 12).attr("text-anchor", "end").text("launches match pain");

  // floor rail
  svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", floorY).attr("y2", floorY).attr("stroke", "var(--line)");
  svg.append("text").attr("class", "axis").attr("x", W - m.r).attr("y", floorY + 12).attr("text-anchor", "end").text("no launches in sample");

  svg
    .selectAll("circle.d")
    .data(points)
    .join("circle")
    .attr("class", "d")
    .attr("data-card", (d) => d.id)
    .attr("cx", (d) => x(d.x))
    .attr("cy", (d) => (d.floor ? floorY - 4 : y(d.y)))
    .attr("r", 3)
    .attr("fill", (d) => (d.floor ? "var(--grey)" : groupColor(d.group)))
    .attr("opacity", (d) => (d.floor ? 0.5 : d.fade))
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id))
    .append("title")
    .text((d) => (d.floor ? `${d.label}: ${d.note}` : `${d.label}: pain ${api.fmt.pct(d.complaintShare, 2)}, launches ${api.fmt.pct(d.launchShare, 2)}`));

  svg.append("text").attr("class", "axis").attr("x", m.l).attr("y", H - 8).text("Complaint share (log)");
  svg.append("text").attr("class", "axis").attr("x", 8).attr("y", m.t).attr("transform", `rotate(-90 12 ${m.t})`).text("Launch share (log)");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Show HN sample n = ${api.fmt.n(meta.n_sampled)} of ${api.fmt.n(meta.n_population)}; match rate ${api.fmt.pct(meta.match_rate?.est, 0)}.`;
  el.appendChild(cap);
}

// Builders vs complainers: log-log complaint share vs sampled launch share,
// y = x diagonal, shaded underbuilt zone, floor rail for zero-launch cards.
// The 8 most underbuilt cards (n >= 100, lowest builders/complainers ratio)
// get direct labels with a simple vertical collision pass.
import { fade } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";

const MIN_N = 100;
const N_LABELS = 8;
const LABEL_GAP = 12; // min px between label baselines

export function prepare(story) {
  const points = story.cards.map((c) => {
    const launch = c.builders?.launch_share?.est ?? null;
    const complaint = c.share?.est ?? 0;
    const zero = !launch || launch <= 0;
    return {
      id: c.id,
      label: c.short,
      group: c.group,
      n_problems: c.n_problems ?? 0,
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
  const labeled = points
    .filter((p) => p.n_problems >= MIN_N && p.ratio != null)
    .sort((a, b) => a.ratio - b.ratio)
    .slice(0, N_LABELS);
  return {
    points,
    labeled,
    meta: {
      n_sampled: story.builders?.n_sampled ?? 0,
      n_population: story.builders?.n_population ?? 0,
      match_rate: story.builders?.match_rate ?? null,
    },
  };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { points, labeled, meta } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 380, m = { l: 45, r: 130, t: 24, b: 40 };
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

  // direct labels for the most underbuilt cards, nudged apart vertically.
  // labels sit right of the point unless that would cross the plot edge.
  const estW = (s) => s.length * 5.2;
  const labelIds = new Set(labeled.map((p) => p.id));
  const toLabel = points
    .filter((p) => labelIds.has(p.id))
    .map((p) => {
      const px = x(p.x), py = p.floor ? floorY - 4 : y(p.y);
      const right = px + 8 + estW(p.label) <= W - m.r - 2;
      return { p, px, py, lx: right ? px + 8 : px - 8, anchor: right ? "start" : "end", ly: py + 3 };
    })
    .sort((a, b) => a.ly - b.ly);
  for (let pass = 0; pass < 40; pass++) {
    let moved = false;
    for (let i = 1; i < toLabel.length; i++) {
      const gap = toLabel[i].ly - toLabel[i - 1].ly;
      if (gap < LABEL_GAP) {
        const push = (LABEL_GAP - gap) / 2;
        toLabel[i - 1].ly -= push;
        toLabel[i].ly += push;
        moved = true;
      }
    }
    // keep labels inside the plot band, clear of the floor caption
    for (const l of toLabel) l.ly = Math.min(Math.max(l.ly, m.t + 6), floorY - 4);
    if (!moved) break;
  }
  const labels = svg.selectAll("g.lb").data(toLabel).join("g").attr("class", "lb");
  labels
    .append("line")
    .attr("x1", (d) => d.px + (d.anchor === "start" ? 4 : -4))
    .attr("y1", (d) => d.py)
    .attr("x2", (d) => d.lx + (d.anchor === "start" ? -2 : 2))
    .attr("y2", (d) => d.ly - 3)
    .attr("stroke", "var(--muted)")
    .attr("stroke-width", 0.5);
  labels
    .append("text")
    .attr("class", "axis")
    .attr("x", (d) => d.lx)
    .attr("y", (d) => d.ly)
    .attr("text-anchor", (d) => d.anchor)
    .text((d) => d.p.label);

  svg.append("text").attr("class", "axis").attr("x", m.l).attr("y", H - 8).text("Complaint share (log)");
  // y-axis title rotated inside the left margin, no clipping
  svg.append("text").attr("class", "axis").attr("x", 12).attr("y", (H - m.b + m.t) / 2).attr("text-anchor", "middle").attr("transform", `rotate(-90 12 ${(H - m.b + m.t) / 2})`).text("Launch share (log)");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Show HN sample n = ${api.fmt.n(meta.n_sampled)} of ${api.fmt.n(meta.n_population)}; match rate ${api.fmt.pct(meta.match_rate?.est, 0)}. Labels: 8 most underbuilt problems.`;
  el.appendChild(cap);
}

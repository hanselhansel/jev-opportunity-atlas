// Breadth beeswarm: one dot per card, x = domain entropy. Cards under 100
// problems are omitted. The followed card is outlined.
import { fade, tooFew } from "../lib/glyph.js";
import { groupColor } from "../lib/palette.js";
import { labelFor } from "../lib/labels.js";

const MIN_N = 100;

export function prepare(story) {
  const dots = story.cards
    .filter((c) => c.n_problems >= MIN_N && c.breadth?.entropy)
    .map((c) => ({
      id: c.id,
      label: c.short,
      group: c.group,
      entropy: c.breadth.entropy.est,
      est: c.breadth.entropy,
      fade: fade(c.breadth.entropy),
      sparse: tooFew(c.breadth.entropy),
      domains: Object.entries(c.breadth.domains || {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([k, v]) => `${labelFor(story, "domains", k)} ${Math.round(v * 100)}%`)
        .join(", "),
    }))
    .sort((a, b) => a.entropy - b.entropy);
  return { dots, omitted: story.cards.length - dots.length };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { dots, omitted } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 200;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const x = d3.scaleLinear().domain([0, d3.max(dots, (d) => d.entropy) * 1.05]).range([30, W - 30]);

  // simple collision-free rows: place dots in lanes by order
  const lanes = 8;
  const laneY = d3.scalePoint().domain(d3.range(lanes)).range([30, H - 40]).padding(0.6);
  const placed = [];
  dots.forEach((d) => {
    let lane = 0, tries = 0;
    while (tries < lanes * 2) {
      const px = x(d.entropy);
      const clash = placed.some((p) => p.lane === lane && Math.abs(p.x - px) < 6.5);
      if (!clash) break;
      lane = (lane + 1) % lanes;
      tries++;
    }
    placed.push({ x: x(d.entropy), lane });
    d.y = laneY(lane);
  });

  svg.append("line").attr("x1", 30).attr("x2", W - 30).attr("y1", H - 22).attr("y2", H - 22).attr("stroke", "var(--line)");
  svg.append("text").attr("class", "axis").attr("x", 30).attr("y", H - 8).text("one domain");
  svg.append("text").attr("class", "axis").attr("x", W - 30).attr("y", H - 8).attr("text-anchor", "end").text("all domains");

  svg
    .selectAll("circle.d")
    .data(dots)
    .join("circle")
    .attr("class", "d")
    .attr("data-card", (d) => d.id)
    .attr("cx", (d) => x(d.entropy))
    .attr("cy", (d) => d.y)
    .attr("r", 3.2)
    .attr("fill", (d) => groupColor(d.group))
    .attr("opacity", (d) => d.fade)
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id))
    .append("title")
    .text((d) => `${d.label}: entropy ${d.entropy.toFixed(2)}. Top: ${d.domains}`);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Domain spread per need. ${omitted} small cards omitted (under ${MIN_N} problems).`;
  el.appendChild(cap);
}

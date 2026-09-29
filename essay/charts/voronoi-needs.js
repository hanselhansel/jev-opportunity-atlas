// Needs map: 13 groups and their cards inside one circle, plus a grey
// "not placed" sector. Packed layout stands in for the precomputed Voronoi.
import { fade } from "../lib/glyph.js";
import { groupColor, NOT_PLACED } from "../lib/palette.js";

export function prepare(story) {
  const unplacedShare = story.unplaced?.share?.est ?? 0;
  const groups = story.groups.map((g) => ({
    id: g.id,
    label: g.label,
    value: g.share.est,
    color: groupColor(g.id),
    cards: (g.cards || [])
      .map((id) => story.cards.find((c) => c.id === id))
      .filter(Boolean)
      .map((c) => ({ id: c.id, short: c.short, value: Math.max(c.share.est, 0.0001), sparse: c.share.sparse, share: c.share })),
  }));
  return { groups, unplacedShare };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const data = prepare(story);
  el.innerHTML = "";

  const W = 700, H = 700;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img");

  const root = d3
    .hierarchy({
      children: [
        ...data.groups.map((g) => ({ gid: g.id, label: g.label, children: g.cards.map((c) => ({ ...c, gid: g.id })) })),
        { gid: "__unplaced", label: "Not placed on a card", children: [{ id: "__unplaced", short: "not placed", value: data.unplacedShare }] },
      ],
    })
    .sum((d) => d.value || 0);

  const pack = d3.pack().size([W, H]).padding(4);
  pack(root);

  const node = svg
    .selectAll("g.leaf")
    .data(root.leaves())
    .join("g")
    .attr("class", "leaf")
    .attr("data-card", (d) => d.data.id)
    .attr("transform", (d) => `translate(${d.x},${d.y})`)
    .style("cursor", "pointer")
    .on("click", (e, d) => d.data.id !== "__unplaced" && api.openSheet(d.data.id));

  node
    .append("circle")
    .attr("r", (d) => Math.max(0, d.r - 0.5))
    .attr("fill", (d) => (d.data.gid === "__unplaced" ? NOT_PLACED : groupColor(d.data.gid)))
    .attr("opacity", (d) => (d.data.gid === "__unplaced" ? 0.35 : fade(d.data.share || { est: 0.1, lo95: 0.09, hi95: 0.11 })))
    .attr("stroke", (d) => (d.data.gid === "__unplaced" ? NOT_PLACED : "var(--paper)"))
    .attr("stroke-width", 0.5);

  // group labels on the group circles
  svg
    .selectAll("text.glabel")
    .data(root.children || [])
    .join("text")
    .attr("class", "cell-label glabel")
    .attr("text-anchor", "middle")
    .attr("x", (d) => d.x)
    .attr("y", (d) => d.y - d.r + 12)
    .text((d) => (d.data.gid === "__unplaced" ? `Not placed ${api.fmt.pct(data.unplacedShare, 0)}` : d.data.label))
    .style("pointer-events", "none");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Area is share of all firsthand problems. Grey sector: problems no card matched.";
  el.appendChild(cap);
}

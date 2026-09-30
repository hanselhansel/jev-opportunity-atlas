// Needs map: 13 groups and their cards inside one circle, with the unplaced
// share as a grey sector of the same circle. Layout is a real Voronoi treemap
// (d3-voronoi-treemap, seeded, 60 iterations) computed at mount time.
import { fade } from "../lib/glyph.js";
import { groupColor, NOT_PLACED } from "../lib/palette.js";

export function prepare(story) {
  const unplacedShare = story.unplaced?.share?.est ?? 0;
  const children = story.groups.map((g) => ({
    id: g.id,
    label: g.label,
    short: g.short,
    value: g.share.est,
    children: (g.cards || [])
      .map((id) => story.cards.find((c) => c.id === id))
      .filter(Boolean)
      .map((c) => ({
        id: c.id,
        short: c.short,
        value: Math.max(c.share.est, 0.0001),
        share: c.share,
      })),
  }));
  children.push({ id: "__unplaced", label: "Not placed on a card", value: unplacedShare, children: [{ id: "__unplaced", short: "not placed", value: Math.max(unplacedShare, 0.0001) }] });
  return { tree: { id: "root", children }, unplacedShare };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const data = prepare(story);
  el.innerHTML = "";

  const W = 700, H = 700, cx = W / 2, cy = H / 2, R = 330;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img");

  const circle = d3.range(96).map((i) => {
    const a = (i / 96) * 2 * Math.PI;
    return [cx + R * Math.cos(a), cy + R * Math.sin(a)];
  });
  const root = d3.hierarchy(data.tree).sum((d) => d.value || 0);
  api
    .voronoiTreemap()
    .clip(circle)
    .convergenceRatio(0.01)
    .maxIterationCount(60)
    .prng(d3.randomLcg(0.42))(root);

  const poly = (n) => (n.polygon ? `M${n.polygon.map((p) => p.join(",")).join("L")}Z` : null);
  const leaves = root.leaves();
  const regionArea = new Map((root.children || []).map((g) => [g.data.id, g.polygon ? Math.abs(d3.polygonArea(g.polygon)) : 0]));

  svg
    .selectAll("path.leaf")
    .data(leaves)
    .join("path")
    .attr("class", "leaf")
    .attr("data-card", (d) => d.data.id)
    .attr("d", poly)
    .attr("fill", (d) => (d.data.id === "__unplaced" ? NOT_PLACED : groupColor(d.parent.data.id)))
    .attr("opacity", (d) => (d.data.id === "__unplaced" ? 0.35 : fade(d.data.share || { est: 0.1, lo95: 0.09, hi95: 0.11 })))
    .attr("stroke", "var(--paper)")
    .attr("stroke-width", 0.5)
    .style("cursor", "pointer")
    .on("click", (e, d) => d.data.id !== "__unplaced" && api.openSheet(d.data.id))
    .append("title")
    .text((d) => `${d.data.short}: ${api.fmt.pct(d.value / Math.max(1e-9, root.value), 2)}`);

  // short group labels only where the region is large enough to hold them
  const labelWorth = (root.children || []).filter(
    (g) => (regionArea.get(g.data.id) || 0) > 2600 && g.polygon,
  );
  svg
    .selectAll("text.glabel")
    .data(labelWorth)
    .join("text")
    .attr("class", "cell-label glabel")
    .attr("text-anchor", "middle")
    .attr("x", (d) => d3.polygonCentroid(d.polygon)[0])
    .attr("y", (d) => d3.polygonCentroid(d.polygon)[1])
    .text((d) =>
      d.data.id === "__unplaced"
        ? `not placed ${api.fmt.pct(data.unplacedShare, 0)}`
        : d.data.short || d.data.label,
    )
    .style("pointer-events", "none");

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Voronoi treemap, area is share of all firsthand problems. Grey sector: problems no card matched. Small groups label on tap.";
  el.appendChild(cap);
}

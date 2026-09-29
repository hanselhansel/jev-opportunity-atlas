// Product bundles: bundle cards on the left, an edge circle on the right.
import { groupColor } from "../lib/palette.js";
import { drawGlyph } from "../lib/glyph.js";

export function prepare(story) {
  const byId = Object.fromEntries(story.cards.map((c) => [c.id, c]));
  const bundles = (story.bundles || []).map((b) => ({
    id: b.id,
    label: b.cards.map((id) => byId[id]?.short || id).join(" + "),
    cards: b.cards,
    share: b.share,
    groups_spanned: b.groups_spanned,
    persistence: b.persistence,
  }));
  const edges = (story.edges || []).map((e) => ({ a: e.a, b: e.b, score: e.score }));
  const nodes = story.cards.map((c) => ({ id: c.id, group: c.group, label: c.short }));
  return { bundles, edges, nodes };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { bundles, edges, nodes } = prepare(story);
  el.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;gap:16px;flex-wrap:wrap";
  el.appendChild(wrap);

  // bundle cards
  const list = document.createElement("div");
  list.style.cssText = "flex:1;min-width:230px";
  for (const b of bundles) {
    const card = document.createElement("div");
    card.style.cssText = "border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;cursor:pointer";
    card.dataset.bundle = b.id;
    card.innerHTML = `<strong>${b.label}</strong><br><span class="cell-label">${api.fmt.pct(b.share?.est, 1)} combined · spans ${b.groups_spanned} groups · persists ${Math.round((b.persistence || 0) * 100)}%</span>`;
    card.addEventListener("click", () => highlight(b.cards));
    list.appendChild(card);
  }
  wrap.appendChild(list);

  // circle
  const W = 340, H = 340, R = 150;
  const svg = d3.select(wrap).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).style("max-width", "100%");
  const groups = [...new Set(nodes.map((n) => n.group))];
  const angle = {};
  let cursor = -Math.PI / 2;
  groups.forEach((g) => {
    const members = nodes.filter((n) => n.group === g);
    const span = (members.length / nodes.length) * 2 * Math.PI;
    members.forEach((n, i) => { angle[n.id] = cursor + (i + 0.5) * (span / members.length); });
    cursor += span;
  });
  const pos = (id) => {
    const a = angle[id] ?? 0;
    return [W / 2 + Math.cos(a) * R, H / 2 + Math.sin(a) * R];
  };
  const seen = new Set();
  const links = edges.filter((e) => {
    const k = e.a < e.b ? `${e.a}|${e.b}` : `${e.b}|${e.a}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return angle[e.a] !== undefined && angle[e.b] !== undefined;
  });
  const linkSel = svg
    .selectAll("line.e")
    .data(links)
    .join("line")
    .attr("x1", (d) => pos(d.a)[0]).attr("y1", (d) => pos(d.a)[1])
    .attr("x2", (d) => pos(d.b)[0]).attr("y2", (d) => pos(d.b)[1])
    .attr("stroke", "var(--muted)")
    .attr("stroke-opacity", (d) => 0.05 + 0.3 * d.score);
  const nodeSel = svg
    .selectAll("circle.n")
    .data(nodes)
    .join("circle")
    .attr("data-card", (d) => d.id)
    .attr("cx", (d) => pos(d.id)[0])
    .attr("cy", (d) => pos(d.id)[1])
    .attr("r", 2.4)
    .attr("fill", (d) => groupColor(d.group))
    .attr("opacity", 0.75)
    .on("click", (e, d) => api.openSheet(d.id));

  function highlight(ids) {
    const set = new Set(ids);
    nodeSel.attr("opacity", (d) => (set.has(d.id) ? 1 : 0.15)).attr("r", (d) => (set.has(d.id) ? 4 : 2.4));
    linkSel.attr("stroke-opacity", (d) => (set.has(d.a) && set.has(d.b) ? 0.5 : 0.03));
  }

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Bundles persist across similarity thresholds. Tap a bundle to light its members.";
  el.appendChild(cap);
}

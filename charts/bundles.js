// Product bundles: bundle cards on the left, an edge circle on the right.
// Default edges run inside bundles only; hovering or tapping a node lights
// every edge touching it. Bundles under 50% persistence hide behind a toggle.
import { groupColor } from "../lib/palette.js";

const MIN_PERSIST = 0.5;

export function prepare(story, { showFragile = false } = {}) {
  const byId = Object.fromEntries(story.cards.map((c) => [c.id, c]));
  const bundles = (story.bundles || []).map((b) => ({
    id: b.id,
    label: b.cards.map((id) => byId[id]?.short || id).join(" + "),
    cards: b.cards,
    share: b.share,
    groups_spanned: b.groups_spanned,
    persistence: b.persistence,
    fragile: (b.persistence ?? 0) < MIN_PERSIST,
  }));
  const visible = bundles.filter((b) => showFragile || !b.fragile);
  // intra-bundle edges: both endpoints in the same visible bundle
  const memberOf = {};
  for (const b of visible) for (const id of b.cards) (memberOf[id] = memberOf[id] || []).push(b.id);
  const key = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  const edges = (story.edges || []).map((e) => ({ a: e.a, b: e.b, score: e.score }));
  const seen = new Set();
  const intra = edges.filter((e) => {
    const k = key(e.a, e.b);
    if (seen.has(k)) return false;
    seen.add(k);
    return (memberOf[e.a] || []).some((bid) => (memberOf[e.b] || []).includes(bid));
  });
  const nodes = story.cards.map((c) => ({ id: c.id, group: c.group, label: c.short }));
  return { bundles, visible, insideEdges: intra, edges, nodes, nFragile: bundles.filter((b) => b.fragile).length };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  el.innerHTML = "";
  let showFragile = false;

  const bar = document.createElement("div");
  bar.style.cssText = "margin-bottom:8px";
  el.appendChild(bar);
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;gap:16px;flex-wrap:wrap";
  el.appendChild(wrap);

  function render() {
    const { visible, insideEdges, edges, nodes, nFragile } = prepare(story, { showFragile });
    bar.innerHTML = "";
    wrap.innerHTML = "";
    if (nFragile > 0) {
      const lab = document.createElement("label");
      lab.className = "cell-label";
      lab.style.cssText = "display:inline-flex;gap:6px;align-items:center;cursor:pointer";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = showFragile;
      cb.addEventListener("change", () => { showFragile = cb.checked; render(); });
      lab.append(cb, document.createTextNode(`show fragile bundles (${nFragile} under 50% persistence)`));
      bar.appendChild(lab);
    }

    // bundle cards
    const list = document.createElement("div");
    list.style.cssText = "flex:1;min-width:230px";
    for (const b of visible) {
      const card = document.createElement("div");
      card.style.cssText = "border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;cursor:pointer";
      card.dataset.bundle = b.id;
      if (b.fragile) card.style.borderStyle = "dashed";
      card.innerHTML = `<strong>${b.label}</strong><br><span class="cell-label">${api.fmt.pct(b.share?.est, 1)} combined \u00b7 spans ${b.groups_spanned} groups \u00b7 persists ${Math.round((b.persistence || 0) * 100)}%</span>`;
      card.addEventListener("click", () => highlight(new Set(b.cards)));
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
    const linkSel = svg
      .selectAll("line.e")
      .data(insideEdges.filter((e) => angle[e.a] !== undefined && angle[e.b] !== undefined))
      .join("line")
      .attr("x1", (d) => pos(d.a)[0]).attr("y1", (d) => pos(d.a)[1])
      .attr("x2", (d) => pos(d.b)[0]).attr("y2", (d) => pos(d.b)[1])
      .attr("stroke", "var(--muted)")
      .attr("stroke-opacity", (d) => 0.1 + 0.4 * d.score);
    // ego edges on hover: drawn on demand so all of a card's edges appear
    const egoLayer = svg.append("g");
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
      .on("click", (e, d) => api.openSheet(d.id))
      .on("pointerenter", (e, d) => {
        egoLayer.selectAll("line")
          .data(edges.filter((x) => x.a === d.id || x.b === d.id))
          .join("line")
          .attr("x1", (x) => pos(x.a)[0]).attr("y1", (x) => pos(x.a)[1])
          .attr("x2", (x) => pos(x.b)[0]).attr("y2", (x) => pos(x.b)[1])
          .attr("stroke", "var(--accent)")
          .attr("stroke-opacity", 0.7);
      })
      .on("pointerleave", () => egoLayer.selectAll("line").remove());

    function highlight(set) {
      nodeSel.attr("opacity", (d) => (set.has(d.id) ? 1 : 0.15)).attr("r", (d) => (set.has(d.id) ? 4 : 2.4));
      linkSel.attr("stroke-opacity", (d) => (set.has(d.a) && set.has(d.b) ? 0.6 : 0.03));
    }
  }
  render();

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Edges run inside bundles. Tap a bundle to light members; hover a dot for all its links.";
  el.appendChild(cap);
}

// Role marimekko: column width = group share, stacked height = role mix
// among problems whose commenter states a role. The top 6 roles by share get
// palette colors; the rest merge into a grey "other". Legend below.
import { fade } from "../lib/glyph.js";
import { labelFor } from "../lib/labels.js";

const TOP_ROLES = 6;
// Bottom labels only fit on columns wider than this (viewBox px at W = 700).
export const LABEL_MIN_PX = 80;
// A vertical 10px label needs about 13px of column pitch.
export const VERTICAL_MIN_PITCH = 13;
const VW = 700, EDGE = 10, GAP = 3;

export function prepare(story) {
  // rank roles by share-of-problems aggregated across groups
  const totals = {};
  for (const g of story.groups) {
    for (const [r, est] of Object.entries(story.roles.by_group[g.id] || {})) {
      totals[r] = (totals[r] || 0) + (est?.est ?? 0) * g.share.est;
    }
  }
  const ranked = Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
  const top = ranked.slice(0, TOP_ROLES);
  const roles = [
    ...top.map((id, i) => ({ id, label: labelFor(story, "roles", id), colorIndex: i })),
    { id: "other", label: "Other roles", colorIndex: null },
  ];
  const colorOf = (r) => (top.includes(r) ? top.indexOf(r) : null);

  // placed problems only: column width = group share of placed
  const placedSum = story.groups.reduce((a, g) => a + (g.share?.est ?? 0), 0) || 1;
  const columns = story.groups
    .map((g) => {
      const mix = story.roles.by_group[g.id] || {};
      const tiles = top.map((r) => ({ role: r, label: labelFor(story, "roles", r), share: mix[r]?.est ?? 0, est: mix[r] || null }));
      const topSum = tiles.reduce((a, t) => a + t.share, 0);
      tiles.push({ role: "other", label: "Other roles", share: Math.max(0, 1 - topSum), est: null });
      return {
        id: g.id,
        label: g.short || g.label,
        width: (g.share?.est ?? 0) / placedSum,
        known: story.roles.known_share[g.id] || null,
        tiles: tiles.filter((t) => t.share > 0.001),
      };
    })
    .sort((a, b) => b.width - a.width);
  // pixel layout at the fixed 700 viewBox: label only what actually fits
  const totalW = columns.reduce((a, c) => a + c.width, 0) || 1;
  let cx = EDGE;
  for (const c of columns) {
    c.px = ((VW - 2 * EDGE) * c.width) / totalW - GAP;
    c.x = cx;
    c.labeled = c.px > LABEL_MIN_PX;
    // narrower group columns get a vertical label when their pitch fits one line
    c.vertical = !c.labeled && c.px + GAP >= VERTICAL_MIN_PITCH;
    cx += c.px + GAP;
  }
  const placed = 1 - (story.unplaced?.share?.est ?? 0);
  return { columns, roles, colorOf, placed };
}

const ROLE_COLORS = ["var(--h0)", "var(--h1)", "var(--h2)", "var(--h3)", "var(--h4)", "var(--h5)"];

export function mount(el, story, api) {
  const d3 = api.d3;
  const { columns, roles, colorOf, placed } = prepare(story);
  el.innerHTML = "";
  // room under the body for vertical labels of the narrow columns
  const W = 700, stripH = 26, bodyH = 274;
  const vLen = Math.max(0, ...columns.filter((c) => c.vertical).map((c) => c.label.length));
  const H = stripH + bodyH + Math.max(30, 12 + vLen * 5.6);
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  let tapLabel = null;

  for (const c of columns) {
    const w = c.px;
    const g = svg.append("g").attr("transform", `translate(${c.x},${stripH})`);
    // disclosure strip: share who state a role
    const k = c.known?.est ?? 0;
    g.append("rect").attr("x", 0).attr("y", -stripH + 4).attr("width", w).attr("height", 10).attr("fill", "var(--line)");
    g.append("rect").attr("x", 0).attr("y", -stripH + 4).attr("width", w * k).attr("height", 10).attr("fill", "var(--muted)").append("title").text(`${api.fmt.pct(k, 0)} state a role`);
    // tiles
    let ty = 0;
    for (const t of c.tiles) {
      const th = t.share * bodyH;
      const ri = colorOf(t.role);
      g.append("rect")
        .attr("x", 0).attr("y", ty).attr("width", w).attr("height", Math.max(0, th - 1))
        .attr("fill", ri == null ? "var(--grey)" : ROLE_COLORS[ri])
        .attr("opacity", t.est ? fade(t.est) : 0.5)
        .append("title").text(`${c.label} / ${t.label}: ${api.fmt.pct(t.share, 0)}`);
      ty += th;
    }
    if (c.labeled) {
      g.append("text").attr("class", "cell-label").attr("x", w / 2).attr("y", bodyH + 14).attr("text-anchor", "middle").text(c.label);
    } else if (c.vertical) {
      g.append("text").attr("class", "cell-label").attr("transform", `translate(${w / 2 - 3},${bodyH + 6}) rotate(90)`).attr("text-anchor", "start").text(c.label);
    } else {
      // narrow columns label on hover (title) or tap (transient text below)
      g.append("title").text(c.label);
      g.style("cursor", "pointer").on("click", () => {
        tapLabel?.remove();
        tapLabel = svg.append("text")
          .attr("class", "cell-label")
          .attr("x", c.x + w / 2)
          .attr("y", H - 4)
          .attr("text-anchor", "middle")
          .attr("fill", "var(--accent)")
          .text(c.label);
      });
    }
  }

  // legend: palette order = role rank
  const legend = document.createElement("div");
  legend.className = "legend";
  for (const r of roles) {
    const item = document.createElement("span");
    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.background = r.colorIndex == null ? "var(--grey)" : ROLE_COLORS[r.colorIndex];
    item.append(sw, document.createTextNode(r.label));
    legend.appendChild(item);
  }
  el.appendChild(legend);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Placed problems only (${api.fmt.pct(placed, 0)} of firsthand problems). Role mix among problems whose commenter states a role. Strip: share who state one. The thinnest columns label on hover.`;
  el.appendChild(cap);
}

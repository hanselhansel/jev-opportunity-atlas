// Role marimekko: column width = group share, stacked height = role mix
// among problems whose commenter states a role. The top 6 roles by share get
// palette colors; the rest merge into a grey "other". Legend below.
import { fade } from "../lib/glyph.js";
import { groupColor, NOT_PLACED } from "../lib/palette.js";
import { labelFor } from "../lib/labels.js";

const TOP_ROLES = 6;

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

  const columns = story.groups
    .map((g) => {
      const mix = story.roles.by_group[g.id] || {};
      const tiles = top.map((r) => ({ role: r, label: labelFor(story, "roles", r), share: mix[r]?.est ?? 0, est: mix[r] || null }));
      const topSum = tiles.reduce((a, t) => a + t.share, 0);
      tiles.push({ role: "other", label: "Other roles", share: Math.max(0, 1 - topSum), est: null });
      return {
        id: g.id,
        label: g.short || g.label,
        width: g.share.est,
        known: story.roles.known_share[g.id] || null,
        tiles: tiles.filter((t) => t.share > 0.001),
      };
    })
    .sort((a, b) => b.width - a.width);
  columns.push({ id: "__unplaced", label: "not placed", width: story.unplaced?.share?.est ?? 0, known: null, tiles: [{ role: "unplaced", label: "not placed", share: 1, est: null }] });
  return { columns, roles, colorOf };
}

const ROLE_COLORS = ["var(--h0)", "var(--h1)", "var(--h2)", "var(--h3)", "var(--h4)", "var(--h5)"];

export function mount(el, story, api) {
  const d3 = api.d3;
  const { columns, roles, colorOf } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 330, stripH = 26, gap = 3;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const totalW = columns.reduce((a, c) => a + c.width, 0);
  const x0 = 10, bodyH = H - stripH - 30;

  let cx = x0;
  for (const c of columns) {
    const w = ((W - 20) * c.width) / totalW - gap;
    const g = svg.append("g").attr("transform", `translate(${cx},${stripH})`);
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
        .attr("fill", c.id === "__unplaced" ? NOT_PLACED : ri == null ? "var(--grey)" : ROLE_COLORS[ri])
        .attr("opacity", t.est ? fade(t.est) : 0.5)
        .append("title").text(`${c.label} / ${t.label}: ${api.fmt.pct(t.share, 0)}`);
      ty += th;
    }
    if (w > 40) {
      g.append("text").attr("class", "cell-label").attr("x", w / 2).attr("y", bodyH + 14).attr("text-anchor", "middle").text(c.label);
    } else {
      g.append("title").text(c.label);
    }
    cx += w + gap;
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
  cap.textContent = "Role mix among problems whose commenter states a role. Strip: share who state one. Narrow columns label on hover.";
  el.appendChild(cap);
}

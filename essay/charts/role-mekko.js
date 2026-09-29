// Role marimekko: column width = group share, stacked height = role mix
// among problems whose commenter states a role. Disclosure strip on top.
import { fade } from "../lib/glyph.js";
import { groupColor, NOT_PLACED } from "../lib/palette.js";

const TOP_ROLES = 6;

export function prepare(story) {
  const roleSet = new Set();
  for (const g of story.groups) for (const r of Object.keys(story.roles.by_group[g.id] || {})) roleSet.add(r);
  const roles = [...roleSet].slice(0, TOP_ROLES);
  const columns = story.groups
    .map((g) => {
      const mix = story.roles.by_group[g.id] || {};
      const tiles = roles.map((r) => ({ role: r, share: mix[r]?.est ?? 0, est: mix[r] || null }));
      const topSum = tiles.reduce((a, t) => a + t.share, 0);
      tiles.push({ role: "other", share: Math.max(0, 1 - topSum), est: null });
      return {
        id: g.id,
        label: g.short || g.label,
        width: g.share.est,
        known: story.roles.known_share[g.id] || null,
        tiles: tiles.filter((t) => t.share > 0.001),
      };
    })
    .sort((a, b) => b.width - a.width);
  columns.push({ id: "__unplaced", label: "not placed", width: story.unplaced?.share?.est ?? 0, known: null, tiles: [{ role: "unplaced", share: 1, est: null }] });
  return { columns, roles: [...roles, "other"] };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { columns } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 330, stripH = 26, gap = 3;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const totalW = columns.reduce((a, c) => a + c.width, 0);
  const x0 = 10, bodyH = H - stripH - 30;
  const roleColors = ["var(--h0)", "var(--h1)", "var(--h2)", "var(--h3)", "var(--h4)", "var(--h5)", "var(--grey)"];

  let cx = x0;
  for (const c of columns) {
    const w = ((W - 20) * c.width) / totalW - gap;
    const g = svg.append("g").attr("transform", `translate(${cx},${stripH})`);
    // disclosure strip
    const k = c.known?.est ?? 0;
    g.append("rect").attr("x", 0).attr("y", -stripH + 4).attr("width", w).attr("height", 10).attr("fill", "var(--line)");
    g.append("rect").attr("x", 0).attr("y", -stripH + 4).attr("width", w * k).attr("height", 10).attr("fill", "var(--muted)").append("title").text(`${api.fmt.pct(k, 0)} state a role`);
    // tiles
    let ty = 0;
    for (const t of c.tiles) {
      const th = t.share * bodyH;
      const ri = t.role === "unplaced" ? roleColors.length - 1 : ["founder", "engineer", "manager", "designer", "data_scientist", "devops"].indexOf(t.role);
      g.append("rect")
        .attr("x", 0).attr("y", ty).attr("width", w).attr("height", Math.max(0, th - 1))
        .attr("fill", c.id === "__unplaced" ? NOT_PLACED : roleColors[ri < 0 ? 6 : ri])
        .attr("opacity", t.est ? fade(t.est) : 0.5)
        .append("title").text(`${c.label} / ${t.role}: ${api.fmt.pct(t.share, 0)}`);
      ty += th;
    }
    if (w > 40) {
      g.append("text").attr("class", "cell-label").attr("x", w / 2).attr("y", bodyH + 14).attr("text-anchor", "middle").text(c.label);
    }
    cx += w + gap;
  }

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Role mix among problems whose commenter states a role. Strip: share who state one.";
  el.appendChild(cap);
}

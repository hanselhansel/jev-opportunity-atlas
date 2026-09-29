// Cost radar small multiples: 4 cost axes per group, outline only, with a
// grey all-problems average shape behind. Group-weighted card costs.
const AXES = ["money", "time", "reliability", "customers"];
const AXIS_LABEL = { money: "money", time: "time", reliability: "reliability", customers: "customers" };

export function prepare(story) {
  // weight each card's cost Ests by its share within its group
  const byGroup = new Map(story.groups.map((g) => [g.id, { g, parts: [] }]));
  for (const c of story.cards) {
    if (!c.costs || c.share.sparse) continue;
    byGroup.get(c.group)?.parts.push(c);
  }
  const panels = [];
  const avg = {};
  for (const [gid, { g, parts }] of byGroup) {
    const tot = parts.reduce((a, c) => a + c.share.est, 0) || 1;
    const vals = {};
    for (const ax of AXES) {
      const est = parts.reduce((a, c) => a + (c.costs[ax]?.est || 0) * c.share.est, 0) / tot;
      const half = Math.sqrt(parts.reduce((a, c) => {
        const e = c.costs[ax];
        const h = e ? (e.hi95 - e.lo95) / 2 : 0;
        return a + (h * c.share.est) ** 2;
      }, 0)) / tot;
      vals[ax] = { est, lo: Math.max(0, est - half), hi: Math.min(1, est + half) };
      (avg[ax] = avg[ax] || []).push(est);
    }
    panels.push({ id: gid, label: g.short || g.label, vals });
  }
  const overall = Object.fromEntries(AXES.map((ax) => [ax, avg[ax].reduce((a, b) => a + b, 0) / avg[ax].length]));
  return { panels, axes: AXES, overall };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { panels, axes, overall } = prepare(story);
  el.innerHTML = "";
  const cols = 5, pw = 132, ph = 132;
  const rows = Math.ceil(panels.length / cols);
  const W = cols * pw, H = rows * ph + 20;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const R = 44;
  const pt = (i, v, cx, cy) => {
    const ang = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
    return [cx + Math.cos(ang) * v * R, cy + Math.sin(ang) * v * R];
  };
  const shape = (vals, cx, cy) =>
    axes.map((ax, i) => pt(i, Math.min(1, vals[ax].est ?? vals[ax]), cx, cy)).map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join("") + "Z";

  panels.forEach((p, i) => {
    const cx = (i % cols) * pw + pw / 2;
    const cy = Math.floor(i / cols) * ph + ph / 2 + 8;
    const g = svg.append("g");
    // grid rings
    [0.5, 1].forEach((r) => {
      g.append("path").attr("d", axes.map((ax, j) => pt(j, r, cx, cy)).map((q, k) => `${k ? "L" : "M"}${q[0]},${q[1]}`).join("") + "Z").attr("fill", "none").attr("stroke", "var(--line)").attr("stroke-width", 0.5);
    });
    // average shape
    g.append("path").attr("d", shape(overall, cx, cy)).attr("fill", "none").attr("stroke", "var(--grey)").attr("stroke-dasharray", "3 3").attr("stroke-width", 1);
    // group shape
    g.append("path").attr("d", shape(p.vals, cx, cy)).attr("fill", "none").attr("stroke", "var(--ink)").attr("stroke-width", 1.8);
    // whiskers
    axes.forEach((ax, j) => {
      const v = p.vals[ax];
      const [x1, y1] = pt(j, v.lo, cx, cy), [x2, y2] = pt(j, v.hi, cx, cy);
      g.append("line").attr("x1", x1).attr("y1", y1).attr("x2", x2).attr("y2", y2).attr("stroke", "var(--muted)").attr("stroke-width", 2).attr("opacity", 0.6);
    });
    g.append("text").attr("class", "cell-label").attr("x", cx).attr("y", cy + R + 14).attr("text-anchor", "middle").text(p.label);
  });
  // axis legend
  axes.forEach((ax, i) => {
    svg.append("text").attr("class", "axis").attr("x", 8 + i * 90).attr("y", 12).text(AXIS_LABEL[ax]);
  });

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Share of the group's problems naming each cost. Dashed: all-problems average. Whiskers: 95%.";
  el.appendChild(cap);
}

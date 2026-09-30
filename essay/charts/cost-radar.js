// Cost radar small multiples: 4 cost axes per group, outline only, with a
// grey all-problems average shape behind. One shared radius tops out at the
// largest group rate rounded up to the next 10%. Axis names sit on each radar.
const AXES = ["money", "time", "reliability", "customers"];
const AXIS_LABEL = { money: "money", time: "time", reliability: "reliab.", customers: "cust." };

export function prepare(story) {
  // weight each card's cost Ests by its share within its group
  const byGroup = new Map(story.groups.map((g) => [g.id, { g, parts: [] }]));
  for (const c of story.cards) {
    if (!c.costs || c.share.sparse) continue;
    byGroup.get(c.group)?.parts.push(c);
  }
  const panels = [];
  const avg = {};
  let maxEst = 0;
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
      maxEst = Math.max(maxEst, est);
      (avg[ax] = avg[ax] || []).push(est);
    }
    panels.push({ id: gid, label: g.short || g.label, vals });
  }
  const overall = Object.fromEntries(AXES.map((ax) => [ax, avg[ax].reduce((a, b) => a + b, 0) / avg[ax].length]));
  const rMax = Math.max(0.1, Math.ceil(maxEst * 10) / 10);
  return { panels, axes: AXES, overall, rMax };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { panels, axes, overall, rMax } = prepare(story);
  el.innerHTML = "";
  const cols = 4, pw = 175, ph = 170;
  const rows = Math.ceil(panels.length / cols);
  const W = cols * pw, H = rows * ph + 10;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const R = 44;
  const pt = (i, v, cx, cy) => {
    const ang = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
    return [cx + Math.cos(ang) * v * R, cy + Math.sin(ang) * v * R];
  };
  const shape = (vals, cx, cy) =>
    axes.map((ax, i) => pt(i, Math.min(1, (vals[ax].est ?? vals[ax]) / rMax), cx, cy)).map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join("") + "Z";

  panels.forEach((p, i) => {
    const cx = (i % cols) * pw + pw / 2;
    const rowTop = Math.floor(i / cols) * ph;
    const cy = rowTop + 102;
    const g = svg.append("g");
    // group name as the panel header
    g.append("text").attr("class", "cell-label").attr("x", (i % cols) * pw + 4).attr("y", rowTop + 14).attr("font-weight", 700).text(p.label);
    // grid rings
    [0.5, 1].forEach((r) => {
      g.append("path").attr("d", axes.map((ax, j) => pt(j, r, cx, cy)).map((q, k) => `${k ? "L" : "M"}${q[0]},${q[1]}`).join("") + "Z").attr("fill", "none").attr("stroke", "var(--line)").attr("stroke-width", 0.5);
    });
    // axis names on each radar, just outside the outer ring
    axes.forEach((ax, j) => {
      const [lx, ly] = pt(j, 1.18, cx, cy);
      const anchor = j === 0 ? "middle" : j === 1 ? "start" : j === 2 ? "middle" : "end";
      g.append("text").attr("class", "axis").attr("x", lx).attr("y", ly + (j === 0 ? -4 : j === 2 ? 9 : 3)).attr("text-anchor", anchor).text(AXIS_LABEL[ax]);
    });
    // average shape
    g.append("path").attr("d", shape(overall, cx, cy)).attr("fill", "none").attr("stroke", "var(--grey)").attr("stroke-dasharray", "3 3").attr("stroke-width", 1);
    // group shape
    g.append("path").attr("d", shape(p.vals, cx, cy)).attr("fill", "none").attr("stroke", "var(--ink)").attr("stroke-width", 1.8);
    // whiskers
    axes.forEach((ax, j) => {
      const v = p.vals[ax];
      const [x1, y1] = pt(j, v.lo / rMax, cx, cy), [x2, y2] = pt(j, v.hi / rMax, cx, cy);
      g.append("line").attr("x1", x1).attr("y1", y1).attr("x2", x2).attr("y2", y2).attr("stroke", "var(--muted)").attr("stroke-width", 2).attr("opacity", 0.6);
    });
  });

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Share of the group's problems naming each cost; outer ring = ${Math.round(rMax * 100)}%. Dashed: all-problems average. Whiskers: 95%.`;
  el.appendChild(cap);
}

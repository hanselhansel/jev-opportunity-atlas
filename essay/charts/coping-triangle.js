// Coping triangle: paid / workaround / abandoned normalized into a
// barycentric point per card. Opacity = share of problems mentioning any.
import { groupColor } from "../lib/palette.js";

const MIN_RESPOND = 50;

export function prepare(story) {
  const cards = [];
  for (const c of story.cards) {
    const k = c.coping || {};
    const n = Math.max(k.paid?.n || 0, k.workaround?.n || 0, k.abandoned?.n || 0);
    const p = k.paid?.est ?? 0, w = k.workaround?.est ?? 0, a = k.abandoned?.est ?? 0;
    const sum = p + w + a;
    if (n < MIN_RESPOND || sum <= 0) continue;
    const t = { pay: p / sum, hack: w / sum, quit: a / sum };
    cards.push({
      id: c.id, label: c.short, group: c.group, n,
      ...t,
      coverage: Math.min(1, n / Math.max(1, c.n_problems)),
      raw: { paid: p, workaround: w, abandoned: a },
    });
  }
  return { cards, corners: ["They pay", "They hack", "They quit"] };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { cards, corners } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 340;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);

  const size = Math.min(H - 60, W * 0.5);
  const ax = W / 2 - size / 2, ay = 20;
  // corners: pay (top-left), hack (top-right), quit (bottom)
  const P = [ax, ay + size], Hk = [ax + size, ay + size], Q = [ax + size / 2, ay];
  const tri = `M${P}L${Hk}L${Q}Z`;
  svg.append("path").attr("d", tri).attr("fill", "none").attr("stroke", "var(--line)");
  svg.append("text").attr("class", "axis").attr("x", P[0]).attr("y", P[1] + 16).attr("text-anchor", "middle").text(corners[0]);
  svg.append("text").attr("class", "axis").attr("x", Hk[0]).attr("y", Hk[1] + 16).attr("text-anchor", "middle").text(corners[1]);
  svg.append("text").attr("class", "axis").attr("x", Q[0]).attr("y", Q[1] - 8).attr("text-anchor", "middle").text(corners[2]);
  // 50% median lines
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  for (const [a, b] of [[P, Hk], [Hk, Q], [Q, P]]) {
    const m = mid(a, b);
    svg.append("line").attr("x1", m[0]).attr("y1", m[1]).attr("x2", ax + size / 2).attr("y2", ay + size / 2 + size * 0.12).attr("stroke", "var(--line)").attr("stroke-dasharray", "2 3");
  }
  const proj = (t) => [
    P[0] * t.pay + Hk[0] * t.hack + Q[0] * t.quit,
    P[1] * t.pay + Hk[1] * t.hack + Q[1] * t.quit,
  ];
  svg
    .selectAll("circle.d")
    .data(cards)
    .join("circle")
    .attr("class", "d")
    .attr("data-card", (d) => d.id)
    .attr("cx", (d) => proj(d)[0])
    .attr("cy", (d) => proj(d)[1])
    .attr("r", 3.4)
    .attr("fill", (d) => groupColor(d.group))
    .attr("opacity", (d) => 0.25 + 0.75 * d.coverage)
    .style("cursor", "pointer")
    .on("click", (e, d) => api.openSheet(d.id))
    .append("title")
    .text((d) => `${d.label}: paid ${api.fmt.pct(d.raw.paid, 0)}, hack ${api.fmt.pct(d.raw.workaround, 0)}, quit ${api.fmt.pct(d.raw.abandoned, 0)}`);

  // side column: top 15 cards by paid rate
  const top = [...cards].sort((a, b) => b.raw.paid - a.raw.paid).slice(0, 15);
  const cx = ax + size + 30;
  svg.append("text").attr("class", "axis").attr("x", cx).attr("y", 24).text("Highest paid rate");
  top.forEach((d, i) => {
    const y = 40 + i * 18;
    svg.append("text").attr("class", "cell-label").attr("x", cx).attr("y", y).text(`${d.label} ${api.fmt.pct(d.raw.paid, 0)}`);
  });

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `Positions are normalized; faint dots have thin evidence (under ${MIN_RESPOND} mentions excluded).`;
  el.appendChild(cap);
}

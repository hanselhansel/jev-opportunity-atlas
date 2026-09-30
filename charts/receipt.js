// Pipeline receipt: a cent grid (1 cell = 1 cent) by phase, plus aligned
// calls-vs-cost slope bars.
const PHASE_COLORS = ["var(--h0)", "var(--h1)", "var(--h2)", "var(--h3)", "var(--h4)", "var(--h5)", "var(--grey)"];

export function prepare(story) {
  const m = story.method;
  const totalCents = Math.round((m.total_usd || 0) * 100);
  const raw = m.runs.map((r) => ({
    phase: r.phase,
    calls: r.calls,
    usd: r.usd,
    p50_ms: r.p50_ms,
    shareCalls: r.calls / Math.max(1, m.total_calls),
    shareCost: r.usd / Math.max(1e-9, m.total_usd),
    per1k: (r.usd / Math.max(1, r.calls)) * 1000,
  }));
  // merge phases under 2% of BOTH calls and cost into "other" so the
  // slope-bar labels cannot collide
  const big = raw.filter((p) => !(p.shareCalls < 0.02 && p.shareCost < 0.02));
  const small = raw.filter((p) => p.shareCalls < 0.02 && p.shareCost < 0.02);
  const phases = [...big];
  if (small.length) {
    phases.push({
      phase: "other",
      calls: small.reduce((a, p) => a + p.calls, 0),
      usd: small.reduce((a, p) => a + p.usd, 0),
      p50_ms: null,
      shareCalls: small.reduce((a, p) => a + p.shareCalls, 0),
      shareCost: small.reduce((a, p) => a + p.shareCost, 0),
      per1k: (small.reduce((a, p) => a + p.usd, 0) / Math.max(1, small.reduce((a, p) => a + p.calls, 0))) * 1000,
      merged: small.map((p) => p.phase),
    });
  }
  return { totalCents, totalCalls: m.total_calls, totalUsd: m.total_usd, totalUsdText: `$${(m.total_usd || 0).toFixed(2)}`, phases };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const data = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 330;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);

  // cent grid (left half)
  const cell = 8, gap = 1, cols = 26;
  const cents = [];
  data.phases.forEach((p, i) => {
    const n = Math.round(p.shareCost * data.totalCents);
    for (let k = 0; k < n; k++) cents.push({ phase: p.phase, i, color: p.merged ? "var(--grey)" : PHASE_COLORS[i % PHASE_COLORS.length] });
  });
  svg
    .selectAll("rect.cent")
    .data(cents)
    .join("rect")
    .attr("x", (d, i) => 10 + (i % cols) * (cell + gap))
    .attr("y", (d, i) => 16 + Math.floor(i / cols) * (cell + gap))
    .attr("width", cell).attr("height", cell).attr("rx", 1)
    .attr("fill", (d) => d.color)
    .append("title")
    .text((d) => `1 cent: ${d.phase}`);
  svg.append("text").attr("class", "axis").attr("x", 10).attr("y", 10).text(`$${data.totalUsd.toFixed(2)} in cents`);

  // slope bars (right half)
  const bx = 420, bw = 60, barH = 280, y0 = 16;
  const callBar = svg.append("g"), costBar = svg.append("g");
  let cy1 = y0, cy2 = y0;
  data.phases.forEach((p, i) => {
    const h1 = p.shareCalls * barH, h2 = p.shareCost * barH;
    const crect = callBar.append("rect").attr("x", bx).attr("y", cy1).attr("width", bw).attr("height", Math.max(0, h1 - 1)).attr("fill", PHASE_COLORS[i % PHASE_COLORS.length]).attr("opacity", 0.85);
    costBar.append("rect").attr("x", bx + bw + 60).attr("y", cy2).attr("width", bw).attr("height", Math.max(0, h2 - 1)).attr("fill", PHASE_COLORS[i % PHASE_COLORS.length]).attr("opacity", 0.85);
    svg.append("line").attr("x1", bx + bw).attr("y1", cy1 + h1 / 2).attr("x2", bx + bw + 60).attr("y2", cy2 + h2 / 2).attr("stroke", PHASE_COLORS[i % PHASE_COLORS.length]).attr("stroke-width", 1.5).attr("opacity", 0.6);
    // label only segments tall enough for text; thin ones carry a title
    if (h1 >= 12) {
      svg.append("text").attr("class", "cell-label").attr("x", bx - 4).attr("y", cy1 + h1 / 2 + 3).attr("text-anchor", "end").text(p.phase);
    }
    crect.append("title").text(p.merged?.join(", ") || p.phase);
    cy1 += h1; cy2 += h2;
  });
  svg.append("text").attr("class", "axis").attr("x", bx).attr("y", y0 + barH + 14).text(`${api.fmt.n(data.totalCalls)} calls`);
  svg.append("text").attr("class", "axis").attr("x", bx + bw + 60 + bw).attr("y", y0 + barH + 14).attr("text-anchor", "end").text(`$${data.totalUsd.toFixed(2)} total`);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Costs are exact. Left bar: share of calls. Right bar: share of spend.";
  el.appendChild(cap);
}

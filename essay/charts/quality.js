// Quality panel: 100-unit arrays for the audit, benchmark and planted test,
// plus wording min-max bars (spread across wordings, not a CI).
export function prepare(story) {
  const q = story.method.quality || {};
  const arrays = [
    { key: "audit_jev", label: "Human audit agreement", value: q.audit_jev, baseline: "always guess the common label" },
    { key: "audit_random", label: "Random agreement baseline", value: q.audit_random, baseline: "chance" },
    { key: "benchmark_acc", label: "Benchmark accuracy", value: q.benchmark_acc, baseline: "published set" },
    { key: "planted_recovery", label: "Planted needs recovered", value: q.planted_recovery, baseline: "90% target" },
  ];
  const wording = {
    screen: (story.method.wording?.screen || []).map((w) => ({ run: w.run, est: w.prevalence?.est, lo: w.prevalence?.lo95, hi: w.prevalence?.hi95 })),
    cardAgreement: story.method.wording?.assign?.card_agreement || [],
    groupAgreement: story.method.wording?.assign?.group_agreement || [],
  };
  return { arrays, wording };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const { arrays, wording } = prepare(story);
  el.innerHTML = "";
  const W = 700, H = 300;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);

  // icon arrays: 2x2 grid of 100-unit waffles
  arrays.forEach((a, i) => {
    const gx = 10 + (i % 2) * 190, gy = 20 + Math.floor(i / 2) * 120;
    const g = svg.append("g").attr("transform", `translate(${gx},${gy})`);
    const lit = Math.round((a.value || 0) * 100);
    for (let c = 0; c < 100; c++) {
      g.append("rect")
        .attr("x", (c % 10) * 9).attr("y", Math.floor(c / 10) * 9)
        .attr("width", 8).attr("height", 8).attr("rx", 1)
        .attr("fill", c < lit ? "var(--h1)" : "var(--line)");
    }
    g.append("text").attr("class", "cell-label").attr("x", 0).attr("y", 102).text(`${a.label}: ${((a.value || 0) * 100).toFixed(1)}%`);
    g.append("text").attr("class", "cell-label").attr("x", 0).attr("y", 114).attr("opacity", 0.7).text(a.baseline);
  });

  // wording min-max bars
  const bx = 420, bw = 240;
  const rows = [
    ...wording.screen.map((w) => ({ label: w.run, lo: w.lo, hi: w.hi, est: w.est })),
    { label: "card agreement", lo: Math.min(...wording.cardAgreement), hi: Math.max(...wording.cardAgreement), dots: wording.cardAgreement },
    { label: "group agreement", lo: Math.min(...wording.groupAgreement), hi: Math.max(...wording.groupAgreement), dots: wording.groupAgreement },
  ];
  const lo = Math.min(...rows.map((r) => r.lo ?? 0)) * 0.9;
  const hi = Math.max(...rows.map((r) => r.hi ?? 1)) * 1.05;
  const x = d3.scaleLinear().domain([Math.max(0, lo), hi]).range([bx, bx + bw]);
  svg.append("text").attr("class", "axis").attr("x", bx).attr("y", 14).text("Spread across wordings (not a CI)");
  rows.forEach((r, i) => {
    const y = 34 + i * 40;
    svg.append("line").attr("x1", x(r.lo)).attr("x2", x(r.hi)).attr("y1", y).attr("y2", y).attr("stroke", "var(--ink)").attr("stroke-width", 2).attr("opacity", 0.5);
    (r.dots || [r.est]).forEach((v) => svg.append("circle").attr("cx", x(v)).attr("cy", y).attr("r", 2.6).attr("fill", "var(--ink)"));
    svg.append("text").attr("class", "cell-label").attr("x", bx).attr("y", y - 6).text(r.label);
  });

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "One array per test. Bars show wording spread, dots are individual runs.";
  el.appendChild(cap);
}

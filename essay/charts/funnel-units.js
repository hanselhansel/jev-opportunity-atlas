// Zooming unit field: funnel steps as dot bands (1 dot = 1,000 comments)
// plus a 12-month column chart of comments.
export function prepare(story) {
  const steps = story.funnel.steps.map((s, i, all) => ({
    key: s.key,
    label: s.label,
    count: s.count,
    retention: i === 0 ? null : s.count / all[i - 1].count,
  }));
  const months = story.funnel.months.map((m) => ({
    period: m.period,
    comments: m.comments,
    firsthand: m.firsthand,
  }));
  return { unit: 1000, steps, months };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const data = prepare(story);
  el.innerHTML = "";

  const W = 700, bandH = 34, gap = 10;
  const H = data.steps.length * (bandH + gap) + 110;
  const canvas = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = "100%"; canvas.style.height = "auto";
  canvas.style.maxWidth = W + "px";
  canvas.setAttribute("viewBox", `0 0 ${W} ${H}`);
  el.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const css = getComputedStyle(el);
  const ink = css.getPropertyValue("--ink").trim() || "#1c2024";
  const muted = css.getPropertyValue("--muted").trim() || "#6b7178";
  const accent = css.getPropertyValue("--accent").trim() || "#b3401e";

  const cell = 4, pitch = 5;
  const cols = Math.floor((W - 150) / pitch);
  data.steps.forEach((s, i) => {
    const y0 = i * (bandH + gap);
    const dots = Math.max(1, Math.round(s.count / data.unit));
    ctx.fillStyle = s.key === "placed" ? accent : ink;
    for (let d = 0; d < dots; d++) {
      const col = d % cols, row = Math.floor(d / cols);
      if (row * pitch > bandH - cell) break;
      ctx.globalAlpha = s.key === "placed" ? 0.95 : 0.35 + 0.55 * (1 - i / data.steps.length);
      ctx.fillRect(150 + col * pitch, y0 + row * pitch, cell, cell);
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = ink;
    ctx.font = "11px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(`${s.label}: ${api.fmt.n(s.count)}`, 0, y0 + 12);
    if (s.retention != null) {
      ctx.fillStyle = muted;
      ctx.fillText(`${api.fmt.pct(s.retention, 0)} kept`, 0, y0 + 24);
    }
  });

  // monthly comment columns
  const my0 = data.steps.length * (bandH + gap) + 30;
  const mx = d3.scaleBand().domain(data.months.map((m) => m.period)).range([40, W - 10]).padding(0.2);
  const my = d3.scaleLinear().domain([0, d3.max(data.months, (m) => m.comments)]).range([my0 + 60, my0]);
  ctx.fillStyle = ink;
  data.months.forEach((m) => {
    ctx.globalAlpha = 0.7;
    ctx.fillRect(mx(m.period), my(m.comments), mx.bandwidth(), my0 + 60 - my(m.comments));
  });
  ctx.globalAlpha = 1;
  ctx.fillStyle = muted;
  ctx.font = "10px sans-serif";
  ctx.fillText("Comments per month", 0, my0 - 14);
  data.months.forEach((m) => ctx.fillText(m.period.slice(1), mx(m.period), my0 + 74));

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = `1 dot = ${api.fmt.n(data.unit)} comments. Counts are exact.`;
  el.appendChild(cap);
}

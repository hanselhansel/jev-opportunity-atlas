// Zooming unit field: funnel steps as dot bands (1 dot = 1,000 comments),
// rescaling to 1 dot = 100 at the sample step. Scrollama drives the stage on
// wide screens; reduced motion and phones get stacked static panels.
// Step text lives in its own column so labels never overlap the dot field.

const MARKERS = {
  all: "counted",
  eligible: "counted",
  screened: "Jev read this sample",
  firsthand: "estimated for all eligible comments",
  placed: "estimated for all eligible comments",
};

// Each step's share is measured against the denominator that makes sense:
// the sample and both estimates are shares of eligible comments, and placed
// is a share of firsthand problems. Sequencing count/prev would divide an
// estimate by the sample size and understate it.
const SHARE_OF = {
  eligible: { base: "all", fmt: (p) => `${p} kept` },
  screened: { base: "eligible", fmt: (p) => `sample: ${p} of eligible` },
  firsthand: { base: "eligible", fmt: (p) => `${p} of eligible comments` },
  placed: { base: "firsthand", fmt: (p) => `${p} of firsthand problems` },
};

const pctAuto = (v) => (v == null ? null : (v * 100 < 10 ? (v * 100).toFixed(1) : String(Math.round(v * 100))) + "%");

export function prepare(story) {
  const countOf = Object.fromEntries(story.funnel.steps.map((s) => [s.key, s.count]));
  const steps = story.funnel.steps.map((s) => {
    const rule = SHARE_OF[s.key];
    const shareText = rule ? rule.fmt(pctAuto(s.count / countOf[rule.base])) : null;
    return {
      key: s.key,
      label: s.label,
      count: s.count,
      shareText,
      marker: MARKERS[s.key] || null,
    };
  });
  const at = (key) => steps.find((s) => s.key === key).count;
  const [all, eligible, screened, firsthand, placed] = [
    at("all"), at("eligible"), at("screened"), at("firsthand"), at("placed"),
  ];
  // one scrolly stage per step; the sample step rescales 1,000 -> 100 per dot
  const stages = [
    { key: "all", unit: 1000, dots: Math.round(all / 1000), lit: Math.round(all / 1000) },
    { key: "eligible", unit: 1000, dots: Math.round(all / 1000), lit: Math.round(eligible / 1000) },
    { key: "screened", unit: 1000, dots: Math.round(all / 1000), lit: Math.round(screened / 1000) },
    { key: "firsthand", unit: 100, dots: Math.round(firsthand / 100), lit: Math.round(firsthand / 100) },
    { key: "placed", unit: 100, dots: Math.round(firsthand / 100), lit: Math.round(placed / 100) },
  ];
  stages.forEach((s) => {
    const step = steps.find((x) => x.key === s.key);
    s.label = step.label;
    s.marker = step.marker;
    s.count = step.count;
  });
  const months = story.funnel.months.map((m) => ({
    period: m.period,
    comments: m.comments,
    firsthand: m.firsthand,
  }));
  return { unit: 1000, steps, stages, months };
}

function makeCanvas(w, h) {
  const canvas = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = "100%";
  canvas.style.maxWidth = w + "px";
  canvas.style.height = "auto";
  canvas.style.aspectRatio = `${w} / ${h}`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return { canvas, ctx };
}

function colorsOf(el) {
  const css = getComputedStyle(el);
  return {
    ink: css.getPropertyValue("--ink").trim() || "#1c2024",
    muted: css.getPropertyValue("--muted").trim() || "#6b7178",
    accent: css.getPropertyValue("--accent").trim() || "#b3401e",
    line: css.getPropertyValue("--line").trim() || "#d9d5cc",
  };
}

// Draw one stage: a dot field plus a unit badge. Dots only; all words stay in
// the steps column or the caption under the field.
function drawStage(ctx, W, H, stage, c) {
  ctx.clearRect(0, 0, W, H);
  const cell = 4, pitch = 5, top = 40;
  const cols = Math.max(10, Math.floor(W / pitch));
  ctx.fillStyle = c.ink;
  ctx.font = "700 13px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(`1 dot = ${stage.unit.toLocaleString("en-US")} comments`, 0, 14);
  ctx.font = "11px sans-serif";
  ctx.fillStyle = c.muted;
  ctx.fillText(`${stage.lit.toLocaleString("en-US")} of ${stage.dots.toLocaleString("en-US")} dots lit`, 0, 30);
  for (let d = 0; d < stage.dots; d++) {
    const col = d % cols, row = Math.floor(d / cols);
    const y = top + row * pitch;
    if (y > H - cell) break;
    const lit = d < stage.lit;
    ctx.fillStyle = lit ? (stage.key === "placed" ? c.accent : c.ink) : c.line;
    ctx.globalAlpha = lit ? 0.9 : 0.45;
    ctx.fillRect(col * pitch, y, cell, cell);
  }
  ctx.globalAlpha = 1;
}

function drawMonths(ctx, W, months, d3, c, api) {
  const top = 16, h = 60;
  const mx = d3.scaleBand().domain(months.map((m) => m.period)).range([0, W - 10]).padding(0.2);
  const my = d3.scaleLinear().domain([0, d3.max(months, (m) => m.comments)]).range([top + h, top]);
  ctx.fillStyle = c.muted;
  ctx.font = "10px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Comments per month", 0, 8);
  ctx.fillStyle = c.ink;
  months.forEach((m) => {
    ctx.globalAlpha = 0.7;
    ctx.fillRect(mx(m.period), my(m.comments), mx.bandwidth(), top + h - my(m.comments));
  });
  ctx.globalAlpha = 1;
  ctx.fillStyle = c.muted;
  ctx.textAlign = "center";
  months.forEach((m) => ctx.fillText(m.period.slice(1), mx(m.period) + mx.bandwidth() / 2, top + h + 12));
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const data = prepare(story);
  el.innerHTML = "";
  const c = colorsOf(el);
  const W = Math.max(300, Math.min(700, el.clientWidth || 700));
  const stacked = api.reducedMotion || W < 600 || !api.scrollama;

  if (stacked) {
    // static fallback: one panel per stage, text under the field
    for (const stage of data.stages) {
      const rows = Math.ceil(stage.dots / Math.floor(W / 5));
      const h = 40 + Math.min(rows * 5, 240) + 8;
      const { canvas, ctx } = makeCanvas(W, h);
      const fig = document.createElement("figure");
      fig.className = "unit-panel";
      fig.style.margin = "0 0 14px";
      const cap = document.createElement("figcaption");
      cap.className = "cap";
      const shareText = data.steps.find((s) => s.key === stage.key)?.shareText;
      cap.textContent =
        `${stage.label}: ${api.fmt.n(stage.count)}` +
        (shareText != null ? ` (${shareText})` : "") +
        (stage.marker ? `. ${stage.marker}.` : ".");
      fig.append(canvas, cap);
      el.appendChild(fig);
      drawStage(ctx, W, h, stage, c);
    }
  } else {
    const wrap = document.createElement("div");
    wrap.className = "scrolly";
    const stepsEl = document.createElement("div");
    stepsEl.className = "scrolly-steps";
    data.stages.forEach((s, i) => {
      const step = document.createElement("div");
      step.className = "step";
      step.dataset.stage = String(i);
      const shareText = data.steps.find((x) => x.key === s.key)?.shareText;
      step.innerHTML =
        `<strong>${s.label}</strong><br>` +
        `<span class="cell-label">${api.fmt.n(s.count)}` +
        (shareText != null ? ` · ${shareText}` : "") +
        `</span>` +
        (s.marker ? `<br><span class="cell-label marker">${s.marker}</span>` : "");
      stepsEl.appendChild(step);
    });
    const graphic = document.createElement("div");
    graphic.className = "scrolly-graphic";
    const gw = Math.max(240, W - 190);
    const { canvas, ctx } = makeCanvas(gw, 300);
    graphic.appendChild(canvas);
    wrap.append(stepsEl, graphic);
    el.appendChild(wrap);
    const paint = (i) => drawStage(ctx, gw, 300, data.stages[i], c);
    paint(0);
    try {
      api
        .scrollama()
        .setup({ step: ".scrolly-steps .step", offset: 0.55 })
        .onStepEnter((r) => paint(Number(r.element.dataset.stage)));
    } catch {
      /* the first panel stays painted */
    }
  }

  // monthly comment columns
  const mh = 96;
  const { canvas, ctx } = makeCanvas(W, mh);
  const block = document.createElement("div");
  block.appendChild(canvas);
  el.appendChild(block);
  drawMonths(ctx, W, data.months, d3, c, api);

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Dot fields rescale 1,000 to 100 comments at the sample step. Counts are exact.";
  el.appendChild(cap);
}

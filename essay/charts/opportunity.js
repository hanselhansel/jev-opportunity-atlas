// Weighted opportunity explorer: presets, sliders, contribution bars,
// rank quantile dots. Founder-set weights re-rank the needs live.
import { groupColor } from "../lib/palette.js";

const COMPONENTS = ["share", "change", "paid", "unsolved", "severity3", "launch_ratio", "reliability", "customers"];
const MIN_N = 200;
const TOP = 20;

function effective(weights) {
  const w = { ...weights };
  const sum = Object.values(w).reduce((a, b) => a + (b || 0), 0);
  if (sum > 0) return { w, notice: false };
  const eq = Object.fromEntries(COMPONENTS.map((k) => [k, 1]));
  return { w: eq, notice: true };
}

export function rank(cards, weights) {
  const { w } = effective(weights);
  const wsum = Object.values(w).reduce((a, b) => a + b, 0) || 1;
  const scored = cards.map((c) => {
    const comp = c.score?.components || {};
    const contrib = {};
    let score = 0, avail = 0;
    for (const k of COMPONENTS) {
      const wt = w[k] || 0;
      if (wt <= 0) continue;
      if (comp[k] == null) continue; // drop missing components, renormalize
      contrib[k] = (comp[k] * wt) / wsum;
      avail += wt;
      score += (comp[k] * wt) / wsum;
    }
    if (avail > 0 && avail < wsum) score = score / (avail / wsum);
    const qs = c.score?.rank_quantiles || [];
    const med = [...qs].sort((a, b) => a - b)[Math.floor(qs.length / 2)] || 0;
    const stable = qs.length ? qs.filter((q) => Math.abs(q - med) <= 3).length / qs.length >= 0.8 : false;
    return { id: c.id, label: c.short, group: c.group, score, contrib, quantiles: qs, stable, hasUnsolved: comp.unsolved != null, n_problems: c.n_problems };
  });
  return scored.sort((a, b) => b.score - a.score);
}

export function prepare(story, weights = story.score_presets?.balanced || {}) {
  const { w, notice } = effective(weights);
  const restricted = (w.unsolved || 0) > 0;
  let pool = story.cards.filter((c) => c.n_problems >= MIN_N && c.score?.components);
  if (restricted) pool = pool.filter((c) => c.score.components.unsolved != null);
  const rows = rank(pool, w).slice(0, TOP).map((r, i) => ({ ...r, rank: i + 1 }));
  return { rows, weights: w, notice, restricted, poolSize: pool.length };
}

export function mount(el, story, api) {
  const d3 = api.d3;
  let weights = { ...(story.score_presets?.balanced || {}) };

  el.innerHTML = "";
  const controls = document.createElement("div");
  const grid = document.createElement("div");
  el.append(controls, grid);

  const presetBar = document.createElement("div");
  presetBar.style.cssText = "display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px";
  for (const name of Object.keys(story.score_presets || {})) {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = name.replaceAll("_", " ");
    b.addEventListener("click", () => { weights = { ...story.score_presets[name] }; syncSliders(); renderRows(); });
    presetBar.appendChild(b);
  }
  controls.appendChild(presetBar);

  const sliders = {};
  const sliderBar = document.createElement("div");
  sliderBar.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px";
  for (const k of COMPONENTS) {
    const lab = document.createElement("label");
    lab.style.cssText = "font-size:12px;color:var(--muted);display:flex;align-items:center;gap:4px";
    lab.textContent = k.replaceAll("_", " ");
    const input = document.createElement("input");
    input.type = "range"; input.min = "0"; input.max = "5"; input.step = "1";
    input.value = String(weights[k] ?? 0);
    input.style.width = "60px";
    let t;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => { weights[k] = Number(input.value); renderRows(); }, 150);
    });
    sliders[k] = input;
    lab.appendChild(input);
    sliderBar.appendChild(lab);
  }
  controls.appendChild(sliderBar);
  const syncSliders = () => { for (const k of COMPONENTS) sliders[k].value = String(weights[k] ?? 0); };

  const noteEl = document.createElement("div");
  noteEl.className = "cap";
  controls.appendChild(noteEl);

  function renderRows() {
    const out = prepare(story, weights);
    grid.innerHTML = "";
    noteEl.textContent = out.notice
      ? "All weights were zero, so every component counts equally."
      : out.restricted
        ? `Only the ${out.poolSize} cards with replies measured are ranked.`
        : `${out.poolSize} cards clear the ${MIN_N}-problem floor.`;

    const W = 700, rowH = 24, H = out.rows.length * rowH + 10;
    const svg = d3.select(grid).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
    const barX = 240, barW = 200, dotsX = barX + barW + 30;
    const row = svg.selectAll("g.r").data(out.rows).join("g").attr("transform", (d, i) => `translate(0,${i * rowH + 10})`).attr("data-card", (d) => d.id).style("cursor", "pointer").on("click", (e, d) => api.openSheet(d.id));
    row.append("rect").attr("class", "hit").attr("x", 0).attr("y", -8).attr("width", W).attr("height", rowH - 4);
    row.append("text").attr("class", "row-label").attr("x", 0).attr("y", 4).text((d) => `${d.rank}. ${d.label}`).attr("fill", (d) => groupColor(d.group));
    // contribution bar
    let acc = 0;
    const keys = Object.keys(out.weights).filter((k) => out.weights[k] > 0);
    row.each(function (d) {
      const g = d3.select(this);
      let x0 = barX;
      keys.forEach((k, i) => {
        const v = d.contrib[k] || 0;
        const wpx = v * barW;
        if (wpx > 0.4) g.append("rect").attr("x", x0).attr("y", -6).attr("width", wpx).attr("height", 12).attr("fill", `var(--h${i % 6})`).attr("opacity", 0.75).append("title").text(`${k.replaceAll("_", " ")}: ${(v * 100).toFixed(0)}%`);
        x0 += wpx;
        acc += v;
      });
    });
    // rank quantile dots
    row.each(function (d) {
      const g = d3.select(this);
      d.quantiles.forEach((q, i) => {
        g.append("circle").attr("cx", dotsX + i * 10).attr("cy", 0).attr("r", 2.6).attr("fill", "var(--ink)").attr("opacity", 0.3 + 0.7 * (1 - Math.min(1, q / 60))).append("title").text(`rank ~${q}`);
      });
      if (d.stable) g.append("text").attr("class", "cell-label").attr("x", dotsX + 205).attr("y", 4).text("stable");
    });
  }
  syncSliders();
  renderRows();
}

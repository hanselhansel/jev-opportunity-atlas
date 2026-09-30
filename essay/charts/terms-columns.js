// Distinctive terms: 13 compact columns, top 8 terms by z. Group labels wrap
// over two short lines (or collapse to a picker under 480px). Each interval is
// a thin bar under its word; no dots inside the column.
import { groupColor } from "../lib/palette.js";

// Wrap a short label over at most 2 lines of <= maxLen chars, splitting at
// spaces, hyphens and underscores first, then hard-wrapping.
function wrapLabel(label, maxLen = 9) {
  const tokens = String(label).split(/[\s\-_]+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (let t of tokens) {
    while (t.length > maxLen) {
      if (cur) lines.push(cur);
      lines.push(t.slice(0, maxLen));
      t = t.slice(maxLen);
      cur = "";
    }
    const cand = cur ? `${cur} ${t}` : t;
    if (cand.length <= maxLen + 1 && lines.length < 2) {
      cur = cand;
    } else {
      if (cur) lines.push(cur);
      cur = t;
    }
    if (lines.length >= 2) break;
  }
  if (cur && lines.length < 2) lines.push(cur);
  if (!lines.length) lines.push(String(label).slice(0, maxLen));
  return lines.slice(0, 2).map((l) => l.slice(0, maxLen + 1));
}

export function prepare(story, width = 700, topN = 8) {
  const groups = story.groups.map((g) => ({
    id: g.id,
    label: g.short || g.label,
    labelLines: wrapLabel(g.short || g.label),
    terms: (story.terms?.[g.id] || []).slice(0, topN).map((t) => ({
      term: t.term,
      z: t.z,
      lo95: t.lo95,
      hi95: t.hi95,
      n_comments: t.n_comments,
      n_authors: t.n_authors,
    })),
  }));
  return { groups, picker: width < 480 };
}

function drawColumn(svg, g, x0, colW, d3, api) {
  const rowH = 24, top = 34;
  const zMax = d3.max(g.terms, (t) => t.hi95) || 1;
  const x = d3.scaleLinear().domain([0, zMax]).range([0, Math.max(30, colW - 16)]);
  const col = svg.append("g").attr("transform", `translate(${x0},0)`);
  g.labelLines.forEach((l, i) => {
    col.append("text")
      .attr("class", "cell-label")
      .attr("y", 10 + i * 11)
      .attr("x", 0)
      .text(l)
      .attr("fill", groupColor(g.id))
      .attr("font-weight", 700);
  });
  const t = col
    .selectAll("g.t")
    .data(g.terms)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${top + i * rowH})`);
  t.append("text")
    .attr("class", "row-label")
    .attr("y", 0)
    .text((d) => (colW < 90 && d.term.length > 7 ? d.term.slice(0, 7) : d.term))
    .append("title")
    .text((d) => `${d.term}: ${d.n_comments} comments, ${d.n_authors} authors`);
  t.append("line")
    .attr("x1", (d) => x(d.lo95))
    .attr("x2", (d) => x(d.hi95))
    .attr("y1", 6)
    .attr("y2", 6)
    .attr("stroke", "var(--muted)")
    .attr("stroke-width", 1.5);
  t.append("line")
    .attr("x1", (d) => x(d.z))
    .attr("x2", (d) => x(d.z))
    .attr("y1", 4)
    .attr("y2", 8)
    .attr("stroke", "var(--ink)")
    .attr("stroke-width", 1.5);
}

export function mount(el, story, api) {
  const d3 = api.d3;
  const width = el.clientWidth || 700;
  const { groups, picker } = prepare(story, width);
  el.innerHTML = "";

  if (picker) {
    // too narrow for columns: one group at a time behind a picker
    const sel = document.createElement("select");
    sel.className = "terms-pick";
    sel.setAttribute("aria-label", "Choose a group");
    groups.forEach((g) => {
      const o = document.createElement("option");
      o.value = g.id;
      o.textContent = g.label;
      sel.appendChild(o);
    });
    const host = document.createElement("div");
    el.append(sel, host);
    const paint = () => {
      host.innerHTML = "";
      const g = groups.find((x) => x.id === sel.value) || groups[0];
      const svg = d3.select(host).append("svg").attr("viewBox", `0 0 340 ${34 + g.terms.length * 24 + 8}`);
      drawColumn(svg, g, 0, 150, d3, api);
    };
    sel.addEventListener("change", paint);
    paint();
  } else {
    const W = 700, colW = (W - 16) / groups.length, rowH = 24;
    const H = 36 + 8 * rowH + 8;
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
    groups.forEach((g, i) => drawColumn(svg, g, 4 + i * colW, colW, d3, api));
  }

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Top distinctive terms per group. Bar under each word: 95% interval on z, tick at z. Only q < 0.05 terms shown.";
  el.appendChild(cap);
}

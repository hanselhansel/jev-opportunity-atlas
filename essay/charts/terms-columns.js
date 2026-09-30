// Distinctive terms: 13 groups in rows of at most 5 columns on desktop and 2
// on phones. Column width is derived from the longest term, so a word is never
// truncated. Header = short group label wrapped to at most 2 lines; each term
// carries one thin 95% interval bar under the word, tick at z.
import { groupColor } from "../lib/palette.js";

const CHAR_PX = 7; // approx px per char at the 12px row-label size
const COL_PAD = 14; // breathing room beside the longest word
const ROW_H = 24;
const HEAD_H = 30;

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
    terms: (story.terms?.[g.id] || []).slice(0, topN).map((t) => ({
      term: t.term,
      label: t.term, // rendered verbatim: never truncate a term
      z: t.z,
      lo95: t.lo95,
      hi95: t.hi95,
      n_comments: t.n_comments,
      n_authors: t.n_authors,
    })),
  }));

  // a column must fit its longest term; reduce columns until it does
  const longest = Math.max(1, ...groups.flatMap((g) => g.terms.map((t) => t.term.length)));
  const needW = longest * CHAR_PX + COL_PAD;
  const inner = Math.max(120, width - 8);
  const maxCols = width >= 480 ? 5 : 2;
  const cols = Math.max(1, Math.min(maxCols, Math.floor(inner / needW)));
  const colW = Math.floor(inner / cols);
  const headerMax = Math.max(6, Math.min(24, Math.floor((colW - 8) / CHAR_PX)));
  for (const g of groups) g.labelLines = wrapLabel(g.label, headerMax);
  const rows = [];
  for (let i = 0; i < groups.length; i += cols) rows.push(groups.slice(i, i + cols));
  return { groups, rows, cols, colW, needW, headerMax, topN, width };
}

function drawColumn(svg, g, x0, y0, colW, d3, api) {
  const col = svg.append("g").attr("transform", `translate(${x0},${y0})`);
  g.labelLines.forEach((l, i) => {
    col.append("text")
      .attr("class", "cell-label")
      .attr("y", 10 + i * 11)
      .attr("x", 0)
      .text(l)
      .attr("fill", groupColor(g.id))
      .attr("font-weight", 700);
  });
  const zMax = d3.max(g.terms, (t) => t.hi95) || 1;
  const x = d3.scaleLinear().domain([0, zMax]).range([0, Math.max(30, colW - 16)]);
  const t = col
    .selectAll("g.t")
    .data(g.terms)
    .join("g")
    .attr("transform", (d, i) => `translate(0,${HEAD_H + i * ROW_H})`);
  t.append("text")
    .attr("class", "row-label")
    .attr("y", 0)
    .text((d) => d.label)
    .append("title")
    .text((d) => `${d.term}: ${d.n_comments} comments, ${d.n_authors} authors`);
  // one thin interval bar under the word, tick at the point estimate
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
  const width = Math.max(280, Math.floor(el.clientWidth || 700));
  const d = prepare(story, width);
  el.innerHTML = "";

  const maxTerms = Math.max(1, ...d.groups.map((g) => g.terms.length));
  const blockH = HEAD_H + maxTerms * ROW_H + 10;
  const H = d.rows.length * blockH + 4;
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${d.width} ${H}`);
  d.rows.forEach((row, ri) =>
    row.forEach((g, ci) => drawColumn(svg, g, 4 + ci * d.colW, ri * blockH, d.colW, d3, api)),
  );

  const cap = document.createElement("div");
  cap.className = "cap";
  cap.textContent = "Top distinctive terms per group. Bar under each word: 95% interval on z, tick at z. Only q < 0.05 terms shown.";
  el.appendChild(cap);
}

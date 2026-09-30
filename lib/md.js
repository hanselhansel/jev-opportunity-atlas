// Tiny markdown-to-HTML renderer. Handles headings, paragraphs, bold, bullet
// lists, and <!-- chart:<id> --> mount placeholders. No dependencies.

const esc = (s) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

const inline = (s) => esc(s).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

const CHART_RE = /^<!--\s*chart:([a-z0-9-]+)\s*-->\s*$/;

export function titleOf(md) {
  for (const line of md.split("\n")) {
    const m = line.trim().match(/^#\s+(.*)$/);
    if (m) return m[1].trim();
  }
  return null;
}

export function chartIds(md) {
  const ids = [];
  for (const line of md.split("\n")) {
    const m = line.trim().match(CHART_RE);
    if (m) ids.push(m[1]);
  }
  return ids;
}

export function render(md) {
  const out = [];
  const lines = md.split("\n");
  let para = [];
  let list = null;

  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${inline(para.join(" "))}</p>`);
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      out.push(`<ul>${list.map((i) => `<li>${inline(i)}</li>`).join("")}</ul>`);
      list = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const t = line.trim();
    const chart = t.match(CHART_RE);
    if (chart) {
      flushPara();
      flushList();
      out.push(`<div class="chart" data-chart="${chart[1]}"></div>`);
      continue;
    }
    if (t.startsWith("<!--")) continue; // other comments are dropped
    if (t === "") {
      flushPara();
      flushList();
      continue;
    }
    const h = t.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      flushPara();
      flushList();
      const level = h[1].length;
      out.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }
    const li = t.match(/^-\s+(.*)$/);
    if (li) {
      flushPara();
      list = list || [];
      list.push(li[1]);
      continue;
    }
    flushList();
    para.push(t);
  }
  flushPara();
  flushList();
  return out.join("\n");
}

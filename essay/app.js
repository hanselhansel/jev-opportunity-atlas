// Essay shell: loads story.json (fixture fallback), renders markdown,
// mounts one chart module per placeholder, wires sheet + drawer + follow mode.
import * as d3 from "d3";
import * as Plot from "@observablehq/plot";
import { voronoiTreemap } from "d3-voronoi-treemap";
import scrollama from "scrollama";
import { render, titleOf } from "./lib/md.js";
import { createSheet } from "./lib/sheet.js";
import * as profile from "./charts/profile.js";

const errslot = document.getElementById("errslot");
const note = (msg) => {
  errslot.textContent = (errslot.textContent + " " + String(msg)).slice(0, 500);
};
window.addEventListener("error", (e) => note(e.message));
window.addEventListener("unhandledrejection", (e) => note(e.reason));

const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function fetchJson(url, fallbackUrl) {
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(String(r.status));
    return await r.json();
  } catch {
    const r = await fetch(fallbackUrl);
    return await r.json();
  }
}
async function fetchText(url, fallbackUrl) {
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(String(r.status));
    return await r.text();
  } catch {
    const r = await fetch(fallbackUrl);
    return await r.text();
  }
}

const fmt = {
  pct: (x, d = 1) => (x == null ? "n/a" : (x * 100).toFixed(d) + "%"),
  pp: (x) => (x == null ? "n/a" : (x * 100).toFixed(1) + " pp"),
  n: (x) => (x == null ? "n/a" : x.toLocaleString("en-US")),
  q: (x) => (x == null ? "n/a" : x < 0.001 ? "<0.001" : x.toFixed(3)),
};

const state = { followed: null, listeners: [] };
const sheet = createSheet(document.getElementById("sheet"));

function applyFollow() {
  document.querySelectorAll(".mark-followed").forEach((n) => n.classList.remove("mark-followed"));
  const chip = document.getElementById("follow-chip");
  if (!state.followed) {
    chip.classList.add("hidden");
    return;
  }
  document
    .querySelectorAll(`[data-card="${state.followed}"]`)
    .forEach((n) => n.classList.add("mark-followed"));
  const card = state.story?.cards.find((c) => c.id === state.followed);
  chip.classList.remove("hidden");
  chip.innerHTML = "";
  chip.append(document.createTextNode(`Following ${card ? card.short : state.followed} `));
  const open = document.createElement("button");
  open.className = "link";
  open.textContent = "profile";
  open.addEventListener("click", () => api.openSheet(state.followed));
  const stop = document.createElement("button");
  stop.className = "link";
  stop.textContent = "stop";
  stop.addEventListener("click", () => api.followCard(null));
  chip.append(open, " / ", stop);
  for (const cb of state.listeners) cb(state.followed);
}

const api = {
  d3,
  Plot,
  voronoiTreemap,
  scrollama,
  fmt,
  reducedMotion,
  sheet,
  followCard: (id) => {
    state.followed = id;
    applyFollow();
  },
  followedCard: () => state.followed,
  onFollow: (cb) => state.listeners.push(cb),
  openSheet: (cardId) => {
    const card = state.story?.cards.find((c) => c.id === cardId);
    if (!card) return;
    sheet.open(profile.sheetHtml(card, state.story, fmt));
  },
};

async function main() {
  const [story, md] = await Promise.all([
    fetchJson("data/story.json", "fixtures/story.fixture.json"),
    fetchText("content/story.md", "content/story.fixture.md"),
  ]);
  state.story = story;

  const article = document.getElementById("article");
  article.innerHTML = render(md);
  const h1 = titleOf(md);
  if (h1) document.title = h1;

  // legend popover
  const pop = document.getElementById("legend-pop");
  document.getElementById("legend-btn").addEventListener("click", () => pop.classList.toggle("hidden"));

  // drawer + mindmap
  const drawer = document.getElementById("drawer");
  let mapMounted = false;
  const openDrawer = async () => {
    drawer.classList.add("open");
    if (!mapMounted) {
      mapMounted = true;
      const mod = await import("./charts/mindmap.js");
      mod.mount(document.getElementById("mindmap"), story, api);
      document.getElementById("map-search").addEventListener("input", (e) => {
        mod.filter?.(e.target.value);
      });
    }
  };
  document.getElementById("map-btn").addEventListener("click", openDrawer);
  document.getElementById("drawer-close").addEventListener("click", () => drawer.classList.remove("open"));

  // mount charts
  const slots = [...document.querySelectorAll(".chart[data-chart]")];
  const results = await Promise.allSettled(
    slots.map(async (el) => {
      const id = el.dataset.chart;
      const mod = await import(`./charts/${id}.js`);
      mod.mount(el, story, api);
      el.dataset.rendered = "1";
    }),
  );
  let errors = 0;
  results.forEach((r, i) => {
    if (r.status === "rejected") {
      errors++;
      slots[i].dataset.error = "1";
      note(`chart ${slots[i].dataset.chart}: ${r.reason}`);
    }
  });

  // machine-readable check block for scripts/essay-check.sh
  const check = document.createElement("div");
  check.id = "check-result";
  check.dataset.overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth ? "1" : "0";
  check.dataset.unrendered = String(slots.length - slots.filter((s) => s.dataset.rendered).length);
  check.dataset.errors = String(errors + (errslot.textContent.trim() ? 1 : 0));
  const lap = countLabelOverlaps();
  check.dataset.labeloverlap = String(lap.total);
  check.dataset.overlaps = Object.entries(lap.byChart).filter(([, n]) => n > 0).map(([k, n]) => `${k}:${n}`).join(",");
  document.body.appendChild(check);

  applyFollow();
}

// Count pairs of SVG text elements whose on-screen boxes overlap inside one
// chart. essay-check.sh asserts this is 0 at both render widths.
function countLabelOverlaps() {
  const byChart = {};
  let total = 0;
  for (const chart of document.querySelectorAll(".chart")) {
    const boxes = [];
    for (const t of chart.querySelectorAll("svg text")) {
      const r = t.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) boxes.push(r);
    }
    let n = 0;
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        const ow = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oh = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ow > 3 && oh > 3) n++;
      }
    }
    byChart[chart.dataset.chart || "?"] = n;
    total += n;
  }
  return { total, byChart };
}

main().catch((e) => {
  note(e);
  const check = document.createElement("div");
  check.id = "check-result";
  check.dataset.overflow = "?";
  check.dataset.errors = "fatal";
  document.body.appendChild(check);
});

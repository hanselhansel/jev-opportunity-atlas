// Dev-only render check for the built site. Not run by pytest.
// usage: node scripts/render-check.mjs <url> <width> <height> <light|dark> <out.png> [blockedUrlPattern]
// Emulates a true <width> viewport over CDP (plain `--window-size` has a 500 px
// floor on macOS), forces the color scheme, waits for Observable cells to settle,
// then prints a JSON audit (banner, errors, horizontal overflow, contrast) and
// writes a full-page screenshot.
import {spawn} from "node:child_process";
import {writeFileSync} from "node:fs";

const CHROME =
  process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [url, width, height, scheme, out, block] = process.argv.slice(2);
const W = Number(width);
const H = Number(height);
const port = 9400 + Math.floor(Math.random() * 500);
const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=/tmp/atlas-render-${port}`,
    `--window-size=${Math.max(W, 500)},${H}`,
    "about:blank",
  ],
  {stdio: "ignore"}
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets;
for (let i = 0; i < 100 && !targets; i++) {
  try {
    targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  } catch {
    await sleep(200);
  }
}
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const pending = new Map();
const logs = [];
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m.result ?? m.error);
    pending.delete(m.id);
  }
  if (m.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(m.params.type))
    logs.push(`console.${m.params.type}: ${m.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  if (m.method === "Runtime.exceptionThrown")
    logs.push(`exception: ${m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text}`);
});
const send = (method, params = {}) =>
  new Promise((r) => {
    const id = ++seq;
    pending.set(id, r);
    ws.send(JSON.stringify({id, method, params}));
  });
const evaluate = async (expression) =>
  (await send("Runtime.evaluate", {expression, returnByValue: true})).result?.value;

await send("Runtime.enable");
await send("Page.enable");
await send("Network.enable");
if (block) await send("Network.setBlockedURLs", {urls: [block]});
await send("Emulation.setDeviceMetricsOverride", {width: W, height: H, deviceScaleFactor: 1, mobile: W < 640});
await send("Emulation.setEmulatedMedia", {features: [{name: "prefers-color-scheme", value: scheme}]});
// SLOW=1 throttles the network so the loading state can be captured with SNAP_AT_MS.
if (process.env.SLOW)
  await send("Network.emulateNetworkConditions", {offline: false, latency: 2000, downloadThroughput: 20000, uploadThroughput: 20000});
await send("Page.navigate", {url});

// Settled = no Observable loading indicator for three consecutive polls,
// unless SNAP_AT_MS asks for a snapshot at a fixed time instead.
const t0 = Date.now();
let stable = 0;
if (process.env.SNAP_AT_MS) await sleep(Number(process.env.SNAP_AT_MS));
while (!process.env.SNAP_AT_MS && Date.now() - t0 < 25000 && stable < 3) {
  await sleep(500);
  const busy = await evaluate(
    `document.readyState !== "complete" || !!document.querySelector("observablehq-loading")`
  );
  stable = busy === false && Date.now() - t0 > 1500 ? stable + 1 : 0;
}
const settledMs = Date.now() - t0;

const audit = await evaluate(`(() => {
  const W = innerWidth;
  const cv = document.createElement("canvas");
  cv.width = cv.height = 1;
  const ctx = cv.getContext("2d", {willReadFrequently: true});
  const rgba = (c) => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "rgba(0,0,0,0)";
    ctx.fillStyle = c;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, base) => [0, 1, 2].map((i) => top[i] * top[3] + base[i] * (1 - top[3])).concat(1);
  const paintsBg = (e) => !(e instanceof SVGElement) || (e instanceof SVGSVGElement && !(e.parentElement instanceof SVGElement));
  const bgOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      if (!paintsBg(e)) continue;
      const c = rgba(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    return layers.reverse().reduce((base, l) => over(l, base), [255, 255, 255, 1]);
  };
  const lum = ([r, g, b]) => {
    const f = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const hex = (c) => "#" + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const seen = new Set();
  const fails = [];
  let checked = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement;
    if (!el || seen.has(el) || el.closest("script,style,noscript,template,option,select")) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (!r.width || !r.height || s.visibility === "hidden" || r.right <= 0 || r.left >= W) continue;
    let opacity = 1;
    for (let e = el; e; e = e.parentElement) opacity *= Number(getComputedStyle(e).opacity);
    if (opacity < 0.05) continue;
    const isSvg = el instanceof SVGElement;
    const fg = rgba(isSvg ? s.fill : s.color);
    fg[3] *= opacity * (isSvg ? Number(s.fillOpacity) : 1);
    const bg = bgOf(el);
    const k = ratio(over(fg, bg), bg);
    checked++;
    if (k < 4.5) fails.push({text: n.textContent.trim().slice(0, 40), tag: el.tagName.toLowerCase(), cls: String(el.className?.baseVal ?? el.className).slice(0, 40), fg: hex(over(fg, bg)), bg: hex(bg), ratio: Math.round(k * 100) / 100});
  }
  const offenders = [...document.querySelectorAll("main *, .site-banner")]
    .filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width && r.right > W + 0.5;
    })
    .slice(0, 10)
    .map((e) => ({tag: e.tagName.toLowerCase(), cls: String(e.className?.baseVal ?? e.className).slice(0, 40), right: Math.round(e.getBoundingClientRect().right)}));
  return {
    viewport: W,
    scrollWidth: document.documentElement.scrollWidth,
    dark: matchMedia("(prefers-color-scheme: dark)").matches,
    banner: [...document.querySelectorAll(".site-banner")].map((b) => b.textContent),
    errors: [...document.querySelectorAll(".observablehq--error")].map((e) => e.textContent),
    loading: document.querySelectorAll("observablehq-loading").length,
    tableRows: document.querySelectorAll(".responsive-table tbody tr").length,
    evidenceState: document.querySelector(".evidence-results")?.innerText.slice(0, 120) ?? null,
    offenders,
    contrast: {checked, fails},
  };
})()`);

const metrics = await send("Page.getLayoutMetrics");
const fullH = Math.ceil(metrics.cssContentSize?.height ?? H);
const shot = await send("Page.captureScreenshot", {
  format: "png",
  captureBeyondViewport: true,
  clip: {x: 0, y: 0, width: W, height: Math.min(fullH, 6000), scale: 1},
});
writeFileSync(out, Buffer.from(shot.data, "base64"));
console.log(JSON.stringify({url, scheme, settledMs, ...audit, logs}, null, 1));
ws.close();
chrome.kill();
process.exit(0);

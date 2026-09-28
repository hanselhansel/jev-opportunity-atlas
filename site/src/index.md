# Findings

```js
import {banner, badge} from "./components/badges.js";
import {chart} from "./components/chart.js";
import {rowsOf} from "./components/data.js";
```

```js
const root = display(html`<div><p class="skeleton">Loading findings…</p></div>`);
```

```js
Promise.all([
  FileAttachment("data/meta.parquet").parquet(),
  FileAttachment("data/findings.parquet").parquet(),
  FileAttachment("data/domain_share.parquet").parquet(),
])
  .then(([metaT, findingsT, shareT]) =>
    render(
      Object.fromEntries(rowsOf(metaT).map((r) => [r.key, r.value])),
      rowsOf(findingsT),
      rowsOf(shareT)
    )
  )
  .catch((e) =>
    root.replaceChildren(
      html`<p><em>Could not load site data: ${e.message}</em></p>`
    )
  );
```

```js
function findingCard(f) {
  return html`<div class="finding-card ${f.status === "candidate" ? "candidate" : ""}">
    <div class="finding-status">${f.status}</div>
    <h3 style="margin: 0.2rem 0">${f.title}</h3>
    <p>${f.problem_statement}</p>
    <p class="finding-meta">${f.n_comments} comments · ${f.n_threads} threads ·
      periods ${f.first_period}–${f.last_period} (${f.months_present} months) ·
      lane: ${f.lane}</p>
  </div>`;
}
```

```js
function domainChart(meta, domainShare) {
  const share = domainShare.filter(
    (r) => r.lane === "breadth" && r.period === "all"
  );
  const ok = share.filter((r) => !r.too_few);
  const few = share.filter((r) => r.too_few);
  const maxX = Math.max(0.01, ...ok.map((r) => Number(r.ci_high ?? 0)));
  const hrefFor = (d) =>
    `evidence#lane=breadth&domain=${encodeURIComponent(d)}`;
  return chart({
    title: "Share of comments by domain",
    subtitle: "weighted share with 95% interval",
    denominator: ok[0]?.denominator,
    n: share.reduce((s, r) => s + Number(r.n), 0),
    lane: "breadth",
    meta,
    ariaLabel:
      `Weighted share of comments for ${ok.length} domains; ` +
      `${few.length} domains too few to estimate`,
    plot: {
      width: 660,
      height: share.length * 36 + 40,
      marginLeft: 95,
      x: {label: "share of screened comments", domain: [0, maxX * 1.35], tickFormat: "%"},
      y: {label: null, domain: share.map((r) => r.domain)},
      marks: [
        Plot.ruleX([0]),
        Plot.barX(ok, {
          x: "weighted_share",
          y: "domain",
          fill: "currentColor",
          style: "color: var(--cat-1)",
          href: (r) => hrefFor(r.domain),
        }),
        Plot.barX(few, {
          x: () => maxX * 0.06,
          y: "domain",
          fill: "url(#atlas-hatch)",
          href: (r) => hrefFor(r.domain),
        }),
        Plot.ruleX(ok, {
          x1: "ci_low",
          x2: "ci_high",
          y: "domain",
          stroke: "currentColor",
          style: "color: var(--atlas-fg)",
        }),
        Plot.text(ok, {
          x: "weighted_share",
          y: "domain",
          text: (r) => `${(r.weighted_share * 100).toFixed(1)}%`,
          dx: 8,
          textAnchor: "start",
          fill: "currentColor",
          style: "color: var(--atlas-fg)",
        }),
        Plot.text(few, {
          x: () => maxX * 0.09,
          y: "domain",
          text: () => "too few to estimate",
          textAnchor: "start",
          fill: "currentColor",
          style: "color: var(--atlas-muted)",
        }),
      ],
    },
    rows: share,
    columns: [
      {key: "domain"},
      {key: "n"},
      {
        key: "weighted_share",
        label: "share",
        format: (v) => (v == null ? "" : `${(v * 100).toFixed(1)}%`),
      },
      {key: "badge"},
      {key: "denominator"},
    ],
  });
}
```

```js
function render(meta, findings, domainShare) {
  const nVal = findings.filter((f) => f.status === "validated").length;
  const nCand = findings.filter((f) => f.status === "candidate").length;
  const domains = new Set(findings.map((f) => f.domain));
  const parts = [
    banner(meta),
    html`<p><strong>${findings.length} findings</strong> across
      ${domains.size} domains: ${nVal} validated, ${nCand} candidates.</p>`,
  ];
  if (!findings.length) {
    parts.push(html`<p><em>No findings yet.</em></p>`);
  }
  parts.push(...findings.map(findingCard));
  parts.push(
    html`<h2 style="display:flex;gap:0.5rem;align-items:center">
      Domain share ${badge("estimated")}</h2>`
  );
  parts.push(domainChart(meta, domainShare));
  root.replaceChildren(...parts);
}
```

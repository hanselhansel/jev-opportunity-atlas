# Findings

```js
import {banner, badge} from "./components/badges.js";
import {chart} from "./components/chart.js";
import {metaOf, rowsOf} from "./components/data.js";
```

```js
const root = display(html`<div><p class="skeleton">Loading findings…</p></div>`);
```

```js
Promise.all([
  FileAttachment("data/meta.parquet").parquet(),
  FileAttachment("data/findings.parquet").parquet(),
  FileAttachment("data/domain_share.parquet").parquet(),
  FileAttachment("data/card_share.parquet").parquet(),
  FileAttachment("data/evidence.parquet").parquet(),
])
  .then(([metaT, findingsT, shareT, cardShareT, evidenceT]) =>
    render(
      metaOf(metaT),
      rowsOf(findingsT),
      rowsOf(shareT),
      rowsOf(cardShareT),
      rowsOf(evidenceT)
    )
  )
  .catch((e) =>
    root.replaceChildren(
      html`<p><em>Could not load site data: ${e.message}</em></p>`
    )
  );
```

```js
const POP = "screen_positive";

function pct(v) {
  return v == null ? "n/a" : `${(v * 100).toFixed(1)}%`;
}

function signedPct(v) {
  return v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function sumItems(rows) {
  return rows.reduce((s, r) => s + Number(r.n_items ?? 0), 0);
}

function shareRows(cardShare, level, bucket) {
  return cardShare.filter(
    (r) => r.level === level && r.population === POP && r.bucket === bucket
  );
}
```

```js
const SHARE_COLS = [
  {key: "label", label: "need"},
  {key: "share", format: pct},
  {key: "lo", label: "interval low", format: pct},
  {key: "hi", label: "interval high", format: pct},
  {key: "n_items", label: "items"},
  {key: "n_authors", label: "authors"},
  {
    key: "p_adj",
    label: "p (BH-adj.)",
    format: (v) => (v == null ? "" : Number(v).toFixed(3)),
  },
];
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
function shareBarChart(meta, rows, title, denom, marginLeft) {
  const data = rows.filter((r) => r.share != null);
  const maxX = Math.max(0.01, ...data.map((r) => Number(r.hi ?? r.share ?? 0)));
  return chart({
    title,
    subtitle: "weighted share with 95% interval",
    denominator: denom,
    n: sumItems(data),
    lane: "breadth",
    meta,
    qualifier: rows[0]?.qualifier,
    ariaLabel: `${title}; ${data.length} bars with intervals`,
    plot: {
      width: 660,
      height: data.length * 36 + 40,
      marginLeft,
      x: {
        label: "share of firsthand problems",
        domain: [0, maxX * 1.3],
        tickFormat: "%",
      },
      y: {label: null, domain: data.map((r) => r.label)},
      marks: [
        Plot.ruleX([0]),
        Plot.barX(data, {x: "share", y: "label", fill: "var(--cat-1)"}),
        Plot.ruleX(data, {
          x1: "lo",
          x2: "hi",
          y: "label",
          stroke: "var(--atlas-fg)",
        }),
        Plot.text(data, {
          x: "share",
          y: "label",
          text: (r) => pct(r.share),
          dx: 8,
          textAnchor: "start",
          fill: "var(--atlas-fg)",
        }),
      ],
    },
    rows,
    columns: SHARE_COLS,
  });
}
```

```js
function changeChart(meta, rows, title, denom, marginLeft) {
  const data = rows.filter((r) => r.share != null);
  const changed = data.filter((r) => r.p_adj != null && r.p_adj < 0.05);
  const same = data.filter((r) => !(r.p_adj != null && r.p_adj < 0.05));
  const lim =
    Math.max(
      0.02,
      ...data.flatMap((r) => [
        Math.abs(Number(r.lo ?? 0)),
        Math.abs(Number(r.hi ?? 0)),
        Math.abs(Number(r.share ?? 0)),
      ])
    ) * 1.15;
  return chart({
    title,
    subtitle:
      "H2 minus H1 share with 95% interval · accent rows: changed, p < 0.05",
    denominator: denom,
    n: sumItems(data),
    lane: "breadth",
    meta,
    qualifier: rows[0]?.qualifier,
    ariaLabel:
      `${title}; ${changed.length} of ${data.length} rows ` +
      `changed at p < 0.05`,
    plot: {
      width: 660,
      height: data.length * 34 + 50,
      marginLeft,
      x: {
        label: "change in share of firsthand problems, H2 minus H1",
        domain: [-lim, lim],
        tickFormat: "%",
      },
      y: {label: null, domain: data.map((r) => r.label)},
      marks: [
        Plot.ruleX([0], {strokeDasharray: "4 3", stroke: "var(--atlas-muted)"}),
        Plot.ruleX(same, {
          x1: "lo",
          x2: "hi",
          y: "label",
          stroke: "var(--atlas-muted)",
        }),
        Plot.ruleX(changed, {
          x1: "lo",
          x2: "hi",
          y: "label",
          stroke: "var(--cat-1)",
          strokeWidth: 2,
        }),
        Plot.dot(same, {x: "share", y: "label", fill: "var(--atlas-muted)", r: 4}),
        Plot.dot(changed, {x: "share", y: "label", fill: "var(--cat-1)", r: 5}),
        Plot.text(changed, {
          x: () => lim,
          y: "label",
          text: (r) => signedPct(r.share),
          textAnchor: "end",
          fill: "var(--cat-1)",
        }),
        Plot.text(same, {
          x: () => lim,
          y: "label",
          text: () => "no clear change",
          textAnchor: "end",
          opacity: 0.8,
          fill: "var(--atlas-muted)",
        }),
      ],
    },
    rows,
    columns: SHARE_COLS,
  });
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
          fill: "var(--cat-1)",
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
          stroke: "var(--atlas-fg)",
        }),
        Plot.text(ok, {
          x: "weighted_share",
          y: "domain",
          text: (r) => `${(r.weighted_share * 100).toFixed(1)}%`,
          dx: 8,
          textAnchor: "start",
          fill: "var(--atlas-fg)",
        }),
        Plot.text(few, {
          x: () => maxX * 0.09,
          y: "domain",
          text: () => "too few to estimate",
          textAnchor: "start",
          fill: "var(--atlas-muted)",
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
        format: (v, row) =>
          row.too_few || v == null
            ? "too few to estimate"
            : `${(v * 100).toFixed(1)}%`,
      },
      {key: "badge"},
      {key: "denominator"},
    ],
  });
}
```

```js
function whereTheProblemsAre(meta, cardShare, evidenceRows) {
  const nFh = evidenceRows.filter(
    (r) => r.account_type === "firsthand_account"
  ).length;
  const denom = nFh
    ? `of ${nFh.toLocaleString("en-US")} sampled firsthand problems`
    : "of sampled firsthand problems";
  const byShare = (a, b) => (b.share ?? -1) - (a.share ?? -1);
  const groupAll = shareRows(cardShare, "group", "all").sort(byShare);
  const cardAll = shareRows(cardShare, "card", "all").sort(byShare).slice(0, 20);
  const topIds = new Set(cardAll.map((r) => r.id));
  const groupDiff = shareRows(cardShare, "group", "H2_minus_H1").sort(byShare);
  const cardDiff = shareRows(cardShare, "card", "H2_minus_H1")
    .filter((r) => topIds.has(r.id))
    .sort(byShare);
  const parts = [
    html`<h2 style="display:flex;gap:0.5rem;align-items:center">
      Where the problems are ${badge("estimated")}</h2>`,
  ];
  if (!cardShare.length) {
    parts.push(html`<p><em>No card share table in this build.</em></p>`);
    return parts;
  }
  parts.push(shareBarChart(
    meta, groupAll, "Need groups by share of firsthand problems", denom, 170
  ));
  parts.push(shareBarChart(
    meta, cardAll,
    `Top ${cardAll.length} need cards by share of firsthand problems`,
    denom, 220
  ));
  parts.push(changeChart(
    meta, groupDiff,
    "What changed between halves: need groups",
    denom, 170
  ));
  parts.push(changeChart(
    meta, cardDiff,
    "What changed between halves: top need cards",
    denom, 220
  ));
  return parts;
}
```

```js
function render(meta, findings, domainShare, cardShare, evidenceRows) {
  const nVal = findings.filter((f) => f.status === "validated").length;
  const nCand = findings.filter((f) => f.status === "candidate").length;
  const domains = new Set(findings.map((f) => f.domain));
  const parts = [
    banner(meta),
    html`<p><strong>${findings.length} findings</strong> across
      ${domains.size} domains: ${nVal} validated, ${nCand} candidates.</p>`,
  ];
  parts.push(...whereTheProblemsAre(meta, cardShare, evidenceRows));
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

# Evidence

```js
import {banner} from "./components/badges.js";
import {onHashChange, readState, setState} from "./components/filters.js";
import {metaOf, rowsOf} from "./components/data.js";
import {responsiveTable} from "./components/table.js";
import {commentCard} from "./components/comment.js";
```

```js
const meta = metaOf(await FileAttachment("data/meta.parquet").parquet());
```

```js
display(banner(meta));
```

```js
const state0 = readState(location.hash);
```

```js
const laneInput = Inputs.radio(["breadth", "discovery"], {
  label: "Lane",
  value: state0.lane,
});
laneInput.addEventListener("input", () => setState({lane: laneInput.value}));
const lane = view(laneInput);
```

```js
const evidence = FileAttachment("data/evidence.parquet").parquet().then(
  (t) => ({rows: rowsOf(t), error: null}),
  (error) => ({rows: [], error})
);
```

```js
const cardShare = FileAttachment("data/card_share.parquet").parquet().then(
  (t) => ({rows: rowsOf(t), error: null}),
  (error) => ({rows: [], error})
);
```

```js
const cardLabel = Object.fromEntries(
  cardShare.rows
    .filter((r) => r.level === "card" && r.bucket === "all")
    .map((r) => [r.id, r.short_label ?? r.label])
);
```

```js
const domains = [...new Set(evidence.rows.map((r) => r.domain))].sort();
const domainInput = Inputs.select(["", ...domains], {
  label: "Domain",
  value: state0.domain ?? "",
  format: (d) => d || "All domains",
});
// A trusted (user) change clears deeper breadcrumb levels; a programmatic set
// from a hash restore keeps them.
domainInput.addEventListener("input", (e) =>
  setState(
    e.isTrusted
      ? {domain: domainInput.value || null, subtopic: null, comment: null}
      : {domain: domainInput.value || null}
  )
);
const domain = view(domainInput);
```

```js
onHashChange((s) => {
  if (s.lane !== laneInput.value) {
    laneInput.value = s.lane;
    laneInput.dispatchEvent(new Event("input", {bubbles: true}));
  }
  if ((s.domain ?? "") !== domainInput.value) {
    domainInput.value = s.domain ?? "";
    domainInput.dispatchEvent(new Event("input", {bubbles: true}));
  }
});
```

```js
const hashState = Generators.observe((change) => {
  const on = () => change(readState(location.hash));
  addEventListener("hashchange", on);
  on();
  return () => removeEventListener("hashchange", on);
});
```

The evidence strength score is a weighted mean of six signals. Move a weight to
re-rank; weights are relative and default to equal.

```js
const weightNames = [
  ["specificity", "specificity / 3"],
  ["concrete_task", "concrete task"],
  ["workaround_p", "workaround"],
  ["consequence_any_p", "consequence"],
  ["behavior_any", "behavior"],
  ["timing_current", "timing current"],
];
const weightInputs = weightNames.map(([k, label]) =>
  Inputs.range([0, 2], {value: 1, step: 0.05, label})
);
const weightsPanel = html`<div class="weights-panel filter-row">
  ${weightInputs}</div>
  <p class="too-few-label">strength = Σ wᵢ·xᵢ / Σ wᵢ over
  [specificity/3, concrete_task, workaround_p, consequence_any_p, behavior_any,
  timing_current]</p>`;
display(weightsPanel);
```

```js
const weights = Generators.observe((change) => {
  const on = () => change(weightInputs.map((i) => Number(i.value)));
  weightsPanel.addEventListener("input", on);
  on();
  return () => weightsPanel.removeEventListener("input", on);
});
```

```js
const results = display(html`<div class="evidence-results">
  <p class="skeleton">Loading evidence…</p></div>`);
```

```js
const filtered = evidence.rows.filter(
  (r) =>
    r.lane === lane &&
    (!domain || r.domain === domain) &&
    (!hashState.subtopic || r.subtopic === hashState.subtopic)
);
```

```js
const scored = filtered
  .map((r) => {
    const p = JSON.parse(r.probabilities_json ?? "{}");
    const terms = [
      Number(r.specificity) / 3,
      Number(p.concrete_task ?? 0),
      Number(r.workaround_p),
      Number(r.consequence_any_p),
      Number(p.behavior_any ?? 0),
      Number(p.timing_current ?? 0),
    ];
    const wsum = weights.reduce((a, b) => a + b, 0) || 1;
    const score =
      weights.reduce((s, w, i) => s + w * terms[i], 0) / wsum;
    return {...r, score};
  })
  .sort((a, b) => b.score - a.score);
```

```js
if (evidence.error) {
  results.replaceChildren(
    html`<p class="state-error">Could not load evidence data:
      ${evidence.error.message}</p>`
  );
} else if (!scored.length) {
  results.replaceChildren(
    html`<p><em>No evidence rows for this lane and domain.</em></p>`
  );
} else {
  results.replaceChildren(
    responsiveTable(scored.slice(0, 200), [
      {key: "comment_id", label: "comment"},
      {key: "domain"},
      {
        key: "subtopic",
        format: (v) => cardLabel[v] ?? v ?? "",
        title: (v) => v,
      },
      {key: "period"},
      {key: "score", label: "strength", format: (v) => v.toFixed(2)},
      {key: "evidence_strength", label: "stored", format: (v) => Number(v).toFixed(2)},
      {key: "support_sentence_id", label: "sentence"},
      {key: "human_label", label: "human label"},
    ], {
      onSelect: (r) =>
        setState({
          lane,
          domain: r.domain,
          subtopic: r.subtopic,
          comment: String(r.comment_id),
        }),
    })
  );
}
```

```js
const selected = hashState.comment
  ? evidence.rows.find((r) => String(r.comment_id) === hashState.comment) ?? null
  : null;
```

```js
if (selected) {
  display(commentCard(selected, hashState, meta));
} else if (hashState.comment) {
  display(
    html`<p><em>Comment ${hashState.comment} is not in the evidence table.</em></p>`
  );
} else {
  display(
    html`<p><em>Select a row above to open the evidence detail.</em></p>`
  );
}
```

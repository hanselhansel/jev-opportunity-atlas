# Method

```js
import {banner} from "./components/badges.js";
import {metaOf, rowsOf} from "./components/data.js";
import {responsiveTable} from "./components/table.js";
```

```js
const meta = metaOf(await FileAttachment("data/meta.parquet").parquet());
const runLabels = JSON.parse(meta.run_labels ?? "{}");
const runLabel = (v) => runLabels[v] ?? v;
```

```js
const robustness = FileAttachment("data/robustness.parquet")
  .parquet()
  .then((t) => ({rows: rowsOf(t), error: null}))
  .catch((error) => ({rows: [], error}));
```

```js
display(banner(meta));
```

## What this is

This site summarizes recurring problems that people describe firsthand in
Hacker News comments. It covers a fixed twelve-month window. Every number on it
comes from the pipeline run and snapshot named in the banner above.

## The pipeline

1. **Acquire.** Walk the official HN item API over a fixed id range and store
   the raw responses.
2. **Snapshot.** Freeze a snapshot: normalized comment text, sentence splits,
   thread context, and coverage counts. Nothing is re-fetched after this point.
3. **Sample.** Draw a probability sample of eligible comments. Every sampled
   comment carries a weight, so estimates can be projected back to the frame.
4. **Classify.** TypeSafe Jev answers a fixed question set for each sampled
   comment: is this firsthand, does it name a workaround, a consequence, a
   concrete task, and so on. Every answer is recorded with the model's own
   confidence.
5. **Evaluate.** A subset is labeled by hand. Agreement metrics with intervals
   are published alongside the data.
6. **Publish.** Release checks export the small, text-free tables this site
   reads. No comment text or usernames ship with the site.

## Two lanes

The **breadth** lane answers "how much": weighted shares of comments by domain,
with intervals. When too few sampled comments land in a domain, the bar is
hatched and marked "too few to estimate" rather than showing a precise-looking
number.

The **discovery** lane answers "where to look": evidence rows ranked by a
strength score. Discovery numbers are counts, never prevalence. A ranked list
cannot tell you how common a problem is.

## Reading the numbers

Every chart shows its denominator next to the title. Badges mark how each
figure was produced: **measured** (counted directly), **calculated** (derived
from measured values), **estimated** (projected with an interval), or
**unknown** (we could not tell). Scores shown for comments are as classified by
Jev, and "TypeSafe confidence" is the model's own score, not a human review.
Human labels appear separately when they exist.

On the evidence page, comment text is fetched live from the Hacker News API in
your browser, never from our servers. The fetched text is normalized and hashed
against the hash stored at classification time. If it does not match, we say so
and show no highlight.

## Does the wording matter?

Headline numbers can move when the same question is asked a different way. The
screen and assign steps are rerun on a subsample with reworded questions; this
section reports the prevalence under each wording and how often the reworded
runs agree with the main run on the same comments.

```js
const robustOut = display(html`<div></div>`);
const prevRows = robustness.rows.filter(
  (r) => r.check === "screen_wording" && r.metric === "prevalence"
);
const agreeRows = robustness.rows.filter(
  (r) => r.check === "screen_wording" && r.metric !== "prevalence"
);
const assignRows = robustness.rows.filter((r) => r.check === "assign_wording");
const kids = [];
if (robustness.error) {
  kids.push(
    html`<p><em>Could not load robustness data:
      ${robustness.error.message}</em></p>`
  );
} else if (!robustness.rows.length) {
  kids.push(html`<p><em>No paraphrase reruns yet.</em></p>`);
} else {
  const vals = prevRows.map((r) => r.value).filter((v) => v != null);
  const los = prevRows.map((r) => r.lo).filter((v) => v != null);
  const his = prevRows.map((r) => r.hi).filter((v) => v != null);
  if (prevRows.length && los.length && his.length) {
    kids.push(html`<p>Under ${prevRows.length} question wordings, the share of
      sampled comments classified as firsthand problems runs from
      ${(Math.min(...vals) * 100).toFixed(1)}% to
      ${(Math.max(...vals) * 100).toFixed(1)}%; the intervals together span
      ${(Math.min(...los) * 100).toFixed(1)}% to
      ${(Math.max(...his) * 100).toFixed(1)}%.</p>`);
    kids.push(
      responsiveTable(prevRows, [
        {key: "run_id", label: "wording", format: runLabel},
        {
          key: "value",
          label: "prevalence",
          format: (v) => `${(v * 100).toFixed(1)}%`,
        },
        {key: "lo", label: "interval low", format: (v) => `${(v * 100).toFixed(1)}%`},
        {key: "hi", label: "interval high", format: (v) => `${(v * 100).toFixed(1)}%`},
        {key: "n"},
      ])
    );
  }
  const agree = [...agreeRows, ...assignRows];
  if (agree.length) {
    kids.push(
      html`<p>Agreement between each reworded run and the main run on the same
        comments:</p>`,
      responsiveTable(agree, [
        {key: "check"},
        {key: "run_id", label: "run", format: runLabel},
        {key: "metric"},
        {
          key: "value",
          format: (v) => (v == null ? "n/a" : Number(v).toFixed(3)),
        },
        {key: "n"},
      ])
    );
  }
}
robustOut.replaceChildren(...kids);
```

## Limits

- HN comments only; not market demand.
- The window is fixed. Nothing here says anything about before or after it.
- Classifications are model outputs with published agreement metrics, not
  ground truth.
- Findings marked "candidate" have not been validated against a second pass.

This site is not affiliated with Hacker News or Y Combinator.

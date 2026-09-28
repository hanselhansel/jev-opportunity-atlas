# Method

```js
import {banner} from "./components/badges.js";
```

```js
const meta = Object.fromEntries(
  (await FileAttachment("data/meta.parquet").parquet()).map((r) => [r.key, r.value])
);
```

${banner(meta)}

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

## Limits

- HN comments only; not market demand.
- The window is fixed. Nothing here says anything about before or after it.
- Classifications are model outputs with published agreement metrics, not
  ground truth.
- Findings marked "candidate" have not been validated against a second pass.

This site is not affiliated with Hacker News or Y Combinator.

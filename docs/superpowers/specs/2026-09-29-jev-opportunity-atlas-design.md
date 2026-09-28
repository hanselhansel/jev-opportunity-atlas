# Jev Opportunity Atlas: design

Status: draft for Hansel's review, 2026-09-29 (SGT). Tier: Deep (public repo, secrets,
new architecture, public claims on X).

## 1. Goal and success

Find recurring, unmet problems in one year of Hacker News comments and share them on X
as evidence-backed startup hypotheses. The Jev story is built in: what TypeSafe's Jev
model got right and wrong, what it cost, and how fast it ran. Every public number is
reproducible from saved answers and traceable to a run.

Success means all of these hold:

1. 3 to 5 candidate findings, each with independent evidence across threads and time,
   contradicting evidence, open unknowns, and one customer-discovery question.
2. Jev quality measured on a held-out set of Hansel's blind labels, with a keyword
   baseline on the same records.
3. Cost and time reported at attempt level, with unknowns shown as unknown.
4. A public static atlas and repo that a stranger can replay without HN or Jev calls.
5. A claims ledger backing every number in the X thread.

Non-goals: market sizing, willingness-to-pay claims, a general HN census beyond the
frozen window, a hosted app that can spend money.

## 2. Decisions

| Area | Decision |
|---|---|
| Source | Hacker News, official Firebase API for the frame, Algolia for discovery search only |
| Window | [2025-09-28T00:00Z, 2026-09-28T00:00Z). Shifted one day earlier than the handoff because its end was still in the future at start |
| Jev budget | Pilot only, up to $1. Hansel sets the main cap after the pilot report |
| Jev access | Direct TypeSafe key in macOS Keychain (`typesafe-jev-api-key`). Rotation recommended because the key was pasted in chat |
| Model | `jev-1.13.0` pinned. Smoke test 2026-09-28 confirmed the pin, `x-typesafe-request-id`, and usage fields |
| Repo | `hanselhansel/jev-opportunity-atlas`, public, created only after publication checks pass |
| HN text | Not redistributed in bulk. Public bundle ships IDs, labels, hashes, aggregates, and a rehydrate script. Findings quote short spans with links |
| Atlas | Static site (Observable Framework, DuckDB-WASM), same build locally and on GitHub Pages |
| Paid actions | CLI only, with a cost estimate and a confirm step. The site never calls Jev |
| Human audit | About 3 hours, about 450 blind labels |
| Disclosure | No TypeSafe affiliation. Hansel pays for all usage |
| Build | Devin CLI lanes on `fusion-claude-opus-5-5-high-sidekick-swe-2-high`, falling back to `swe-2-max` on usage errors. Release via gstack `/ship` then `/land-and-deploy` |

## 3. Corpus (milestone 1, running)

Frame: every HN item ID from 45,395,433 to 49,877,056. That is the first and last
in-window IDs located by binary search on item `time`, plus a 5,000-ID margin each
side. Boundaries are frozen in `data/raw/<snapshot>/boundaries.json`.

Acquisition: 449 immutable shards of 10,000 IDs, zstd JSONL, SHA-256 per shard. Six
worker processes at 48 connections each (about 800 IDs/s; one process tops out near
190 IDs/s because the HTTP client degrades at higher concurrency). Every ID ends in one
state: `ok`, `deleted`, `dead`, `null`, or `failed`. Each record keeps attempts,
backoff, timing, and the response hash. Resume refetches only missing, corrupt, or
failed work.

Probe results (30,000 IDs): 0 retries, about 2 MB per shard, about 90% comments,
about 3% deleted, about 4% dead. Projected: about 0.9 GB compressed, about 4.0M
comments.

Canonical snapshot (Parquet, built after the walk):

- `comments`: id, time, parent_id, story_id, depth, text_html, text_norm,
  sentence list with stable sentence IDs, author (local only), thread_type,
  in_window flag, language, word count.
- `stories`: id, time, title, url, score, descendants, thread_type, in_window flag.
- `ancestors`: parent chains, including out-of-window context items, flagged.
- `coverage`: counts by state, type, month, exclusion reason.

Thread type comes from the root story: `ask_hn`, `show_hn`, `launch_hn`, `tell_hn`,
`story`, `poll`. Job posts take no comments and are listed in coverage only.

Eligible population: comments with in-window `time`, state `ok`, non-empty text,
English by a local detector (lingua, pinned). Dead and deleted comments, non-English
comments, and empty text are excluded and counted. The frame is named everywhere as
"HN comments retrievable from the official API on 2026-09-28", never "all of HN".

Algolia hits in the discovery lane are matched back by ID. Items outside the frame go
into a versioned supplemental snapshot, never into the breadth frame.

## 4. Units, lanes, and denominators

Unit of analysis: one eligible comment, judged with bounded context (the comment, its
parent text truncated to 1,500 characters, and the story title).

Two lanes, never mixed in one number:

- **Breadth lane.** A probability design over the eligible population. Every record
  carries its inclusion probability. Estimates are weighted.
- **Discovery lane.** Purposeful searches that deepen a pattern. Results are ranked by
  evidence strength and never reported as prevalence.

Breadth design, sized after the pilot:

- Option A, census screen: every eligible comment gets the screening questions.
  Inclusion probability 1. Sampling error is zero; classification error remains and
  is reported from the audit.
- Option B, stratified sample: strata = month (12) x thread type (6) x thread
  engagement tercile (story `descendants`, terciles computed once on the frame and
  frozen). Simple random sampling within strata with a stored seed. Weight = N_h / n_h.
- Both options use the same pipeline and store the same manifest: seed, algorithm,
  stratum counts, selected IDs, and probabilities. Every expansion is a new manifest
  version with recomputed probabilities.

Uncertainty: cluster bootstrap that resamples threads within strata (2,000
replicates), because comments in one thread are dependent. Distinct-author counts are
reported as corroboration, not as a count of people. Categories with fewer than 30
weighted-sample hits show a count and "too few to estimate" instead of a percentage.

Denominators are always named in the UI and the claims ledger: eligible comments,
screened comments, firsthand-problem comments, threads, or authors.

## 5. Jev questions

State sent to Jev (JSON, fields named in instructions):

```json
{"comment": "...", "parent": "...", "story_title": "...", "thread_type": "ask_hn"}
```

Comment text is untrusted data. Instructions always name `comment` explicitly, and
the pilot includes injected-instruction test cases (Jev jaggedness item 6).

**Screen set** (every comment in the breadth set, v1 frozen after the pilot):

| id | type | question |
|---|---|---|
| firsthand_problem | noul | Does `comment` describe a problem the author personally experienced? |
| account_type | choice | firsthand account, secondhand report, general opinion, product pitch or self-promotion, joke or sarcasm, question or request, other |
| domain | choice | provisional broad domains from taxonomy v0, plus `other`, `mixed`, `unclear` |

**Deep set** (comments above the screen threshold, plus a random slice below it to
measure what the gate drops):

| id | type | notes |
|---|---|---|
| concrete_task | noul | a concrete task or workflow is named |
| timing | choice | current or recent, historical, hypothetical, unclear |
| workaround | noul | a workaround is explicitly described |
| cost_time / cost_money / cost_reliability / cost_customer / cost_operational | noul x5 | one question per consequence type |
| paid / switched / tried_alternatives / abandoned | noul x4 | kept separate on purpose |
| resolution | choice | resolved, unresolved, unclear, using the supplied context only |
| user_role | choice | provisional roles plus `other`, `mixed`, `unclear` |
| specificity | score | 4-level rubric: vague, named problem, named problem + context, named problem + context + measurable detail |
| support_sentence | choice | options are sentence IDs `s0..sN` (max 255). Code checks each chosen ID exists and quotes only real text |

Rules from the Jev docs (checked 2026-09-28): one judgment per question, arithmetic and
dates in code, minimal state, no reliance on noul/choice consistency, noul thresholds
tuned per question and never reused across question types. `confidence` exists only
for choice and score and is reported as TypeSafe defines it, separate from
probabilities.

Screen threshold: picked on pilot labels to reach at least 0.90 recall on
`firsthand_problem`, then checked on the held-out set.

Evidence strength (code, weights shown in the UI, default equal weights): specificity,
concrete_task, workaround, any explicit consequence, any explicit behavior, current
timing. No hidden "opportunity score".

Measured cost input: the smoke test used 366 input tokens for a one-sentence comment
and two questions, so question text drives cost. The pilot measures tokens per call
for each question set before any budget request.

## 6. Topics and findings

Taxonomy v0: Hansel reviews about 300 random pilot comments flagged firsthand.
Claude (Opus 5.5, this session, subscription, not metered per call) proposes candidate
domain and role names; Hansel edits and approves. The auxiliary model, its inputs, and
its outputs are recorded in `taxonomy/v0/provenance.json`. Jev never names categories.

Drilldown: when Hansel opens a domain, a random sample of that domain's evidence is
reviewed, subtopics are proposed and approved as taxonomy v0.1, and Jev classifies the
domain subset against them. Each drilldown stores its subset manifest and taxonomy
version, and the breadcrumb path is kept.

Recurring problems: within a subtopic, reviewed evidence yields candidate problem
statements. Jev then answers one noul per comment: "Does `comment` describe this
problem: <statement>?" over the subtopic subset. Code counts matches, independent
threads, distinct authors, months present, and contradicting or resolved cases.

Finding card: user and workflow, concrete problem, current workarounds, independent
evidence (thread and month spread), contradicting evidence, evidence dates, unknowns,
customer-discovery question, lane, run ID, model version.

## 7. Evaluation

Labeler: a small local Streamlit app. It shows comment and context first and never
shows Jev's answer during blind labeling. Stores reviewer, rubric version, timestamps,
and time spent.

Sets:

- Calibration (about 150): random pilot comments. Used to tune wording and the
  threshold. Never used for reported metrics.
- Held-out (about 300): drawn after questions freeze, from a separate seed, stratified
  by Jev prediction (confident positive, confident negative, uncertain band) with
  known sampling rates, so population precision and recall can be estimated with
  weights. Includes high-confidence predictions.
- Edge cases (about 50): enriched sarcasm, pitches, resolved problems, missing
  parents, injected instructions. Reported separately, never mixed into population
  metrics.

Metrics: precision, recall, F1 for `firsthand_problem` with bootstrap intervals;
accuracy and confusion tables for choices; a reliability diagram with bin counts; a
false-negative gallery. Keyword baseline (a fixed regex list for pain words) runs on
the same held-out records. No other paid LLM baseline.

## 8. Cost and time accounting

Ledger: append-only JSONL per run, one row per network attempt, with a logical-call
ID. Fields: run_id, logical_call_id, attempt, request_id, model_requested,
model_returned, question_set_version, question_count, input_hash, started_at,
ended_at (UTC), monotonic durations (queue, request, backoff), http_status,
error_type, validation result, input_tokens, output_tokens, cache disposition, price
version, computed cost.

The Jev client calls the HTTP API directly with httpx and implements its own retries,
because the SDK retries twice by default and would hide attempts.

Cost classes:

- Calculated: reported input tokens x price table row (`configs/prices.toml`,
  `jev-1.13.0`, $0.042 per million input, output free, checked 2026-09-28).
- Reconciled: set only when TypeSafe dashboard or billing evidence covers an isolated
  window with only this project's traffic. Otherwise "not reconciled".
- Unknown: any attempt with null usage, a timeout, or a lost response. Counted and
  shown, never zero.

Budget guard: before dispatch, spend = calculated + reserved (estimated tokens of
in-flight calls) + unknown attempts x worst-case estimate. Dispatch stops when the
next batch would exceed the cap. Progress persists, so restart never repeats a
completed call.

Cache: key = SHA-256 of canonical JSON (state, questions, question version, pinned
model). A hit is logged as a replay with zero new cost and keeps the original cost
reference. Replays never count as latency benchmarks.

Time: phase events (acquire, snapshot, pilot, screen, deep, aggregate, site build,
human review) with wall time. Per-attempt p50 and p95 latency, throughput, and
concurrency. Named events: first candidate finding, first human-validated finding.
Runs are labeled cold, fresh-on-cached-source, or replay.

Dashboard numbers: total cost, cost per screened comment, cost per validated finding
shown as shared base cost plus incremental drilldown cost. No per-finding cost claim
where attribution is arbitrary.

## 9. Security and publication

- Key: read from Keychain at call time, env var fallback. Never logged. `.env.example`
  has placeholders only.
- Safe serializer: ledger rows are built from an explicit field list. No headers,
  no SDK objects, no URLs with credentials.
- Scanning: gitleaks plus a custom rule for `apikey_[0-9a-f]{36}_[0-9a-f]{64}` runs in a
  pre-commit hook, in CI, and in `atlas publish`. A hit blocks. Tests use a fake
  canary key with the same shape.
- Devin lanes: canary key and a local mock Jev server only. No lane reads Keychain.
- HN content scan: the same scanner and a PII pass over comment text. Hits are never
  quoted and are listed by ID in a restricted local report.
- Public bundle (GitHub Release assets, allowlisted): snapshot manifest, coverage,
  sample manifests, Jev answers keyed by comment ID, text hashes, aggregates, ledger
  without secrets, audit labels, claims ledger. No HN text, no usernames.
- Rehydrate: `atlas rehydrate` refetches text from the official API and checks
  hashes. It reports the share that no longer matches (edits, deletions). All charts
  replay from saved answers regardless.
- Licenses: code MIT. Derived labels and aggregates CC BY 4.0. HN comments remain their
  authors'; the README says so and links the HN API.
- First push: the repo is created public only after the scan passes on the full
  history.

## 10. Atlas (static site)

Observable Framework site in `site/`. Python data loaders read the run outputs and emit
Parquet. DuckDB-WASM runs in the browser for linked filtering. Same build locally and on
GitHub Pages.

Pages:

1. Coverage: frame, window, states, exclusions, strata.
2. Atlas: domain bars and time trends with a lane selector, denominators, intervals.
3. Topic: subtopics, recurrence over months, thread and author spread, workaround and
   consequence rates.
4. Evidence: comment card with HN link, Jev answers, probabilities, confidence, model
   version, human label if any. Public mode fetches text at view time from the official
   HN API in the reader's browser; local mode reads the local snapshot.
5. Runs: cost, time, latency, retries, failures, cache effect, quality metrics.
6. Reproduce: manifests, checksums, question versions, replay steps.
7. Method: plain-language explainer of the whole pipeline.

Every number carries a badge: measured, calculated, estimated, or unknown. Any mock data
shows a persistent fictional-data banner. The site never mixes runs, question versions,
or lanes in one chart.

Deeper analysis is a CLI command (`atlas drill`), not a site button: it previews the
subset, prints estimated calls and cost, and asks for confirmation.

## 11. X publishing

- Claims ledger: `claims/claims.yaml`. Each entry holds the sentence as posted, the
  number, the query or notebook cell, run ID, lane, denominator, and interval. `atlas
  claims check` recomputes every number from saved answers and fails on drift.
- Chart exports: `atlas export-x` renders 1600x900 PNGs. Footer on every image: source,
  window, n, lane, run ID, "HN comments only; not market demand".
- No usernames or avatars in images. Quotes are short, linked, and never make one
  person the face of a problem.
- Disclosure in the first post and README: "No affiliation with TypeSafe. I paid for
  all usage."
- Dull-result plan: if no finding clears the evidence bar, the thread reports the
  method, the Jev quality and cost results, and the null result.
- Hansel posts. The pipeline only drafts the thread in `claims/thread.md`.

## 12. Repository and commands

```text
src/atlas/
  sources/      acquisition, snapshot build, coverage, Algolia discovery
  sampling/     frame, strata, selection, weights, bootstrap
  inference/    Jev client, ledger, budget guard, cache, question sets
  analysis/     aggregation, evidence strength, drilldown, findings
  evaluation/   labeler app, metrics, keyword baseline
  publication/  allowlist export, secret scan, rehydrate, restore, claims, X export
site/           Observable Framework
configs/        acquisition, sampling, prices, budgets, question sets
manifests/      snapshot, sample, run manifests (small, tracked)
claims/         claims ledger and thread draft
docs/           method, data dictionary, walkthrough, specs, plans
tests/          unit and failure-path tests, mock Jev server
```

Commands: `acquire`, `coverage`, `snapshot`, `verify-snapshot`, `sample`, `pilot`,
`screen`, `deep`, `drill`, `label`, `evaluate`, `analyze`, `replay`, `site`, `export-x`,
`claims check`, `publish`, `rehydrate`, `restore`.

Source files stay under 400 lines. Branches use `feat/`, `fix/`, `chore/`.

## 13. Build plan and gates

| Milestone | Work | Gate |
|---|---|---|
| M1 Corpus | walk (running), snapshot, coverage, restore test | coverage reconciles every ID |
| M2 Pilot | Jev client, ledger, guard, cache, labeler; 2,000-comment stratified pilot; 150 calibration labels; taxonomy v0 | Hansel reads the pilot report and sets the main budget. Spend so far at most $1 |
| M3 Main run | screen (census or sample), deep pass, discovery lane | within cap, zero unexplained unknowns |
| M4 Evaluation | 300 held-out labels, edge cases, baseline | metrics with intervals |
| M5 Findings and atlas | drilldowns, finding cards, site | Hansel validates findings |
| M6 Publish | `/ship`, `/land-and-deploy` (GitHub Pages), release assets, clean restore from the downloaded bundle, X exports | scans clean, restore reproduces the charts |

Parallel Devin lanes after this spec and the plan are approved (disjoint files, frozen
interfaces in the plan): snapshot and sampling; Jev client, ledger, guard, cache, and
mock server; evaluation and labeler; publication and scanning; site shell with
synthetic fixtures. Analysis and findings come after the pilot because they depend on
the frozen questions. One whole-branch review before `/ship`.

## 14. Risks

- Jev may read firsthand problems too literally or miss sarcasm. The pilot measures
  this before money is spent at scale.
- Question text dominates tokens, so a census may cost more than the handoff estimate.
  The pilot report gives measured cost per question set.
- Rate limits are "dynamically adjusting" per TypeSafe docs; a census at 1,200 RPM is
  about 55 hours. The guard throttles and resumes.
- Disk: 14 GiB free. The corpus fits; the acquisition guard refuses to start below
  headroom.
- The pasted Jev key sits in this session's transcript. Rotate before the main run.

# Plan review record: M1 to M2 plan set

Date: 2026-09-29. Reviewed: `docs/superpowers/plans/2026-09-29-*.md` against the approved spec.

## How the review ran

gstack `/autoplan` could not run its phases: its phase-entry guard never finds this
desktop session's transcript root (desktop writes attachment records before the first
user message, so ancestry never roots). The same four lenses ran directly instead:

| Lens | Reviewer | Status |
|---|---|---|
| CEO / strategy | Claude subagent (fresh context) + Codex | completed |
| Design (site) | Claude subagent + Codex | completed |
| Developer experience | Claude subagent + Codex | completed |
| Engineering (last) | Claude subagent + Codex | completed |

Codex report: `2026-09-29-plan-review-codex.md`. Claude reports were delivered in session.

## Consensus (raised independently by 2 or more reviewers)

| Issue | Codex | Claude CEO/DX | Claude Eng |
|---|---|---|---|
| Runner crash can lose answers or repeat paid calls | yes | yes | yes |
| Screen and deep in one run break the run manifest | yes | no | yes |
| Budget guard ignores retries and spend across runs | yes | no | yes |
| Taxonomy provenance would publish HN text | yes | yes | yes |
| Secret preview redacts only the first match; hook scans working tree | yes | yes | yes |
| Calibration labels not drawn from the pilot sample | yes | yes | yes |
| Too few positives in 150 random calibration labels | no | yes | yes |
| Held-out metrics need selection weights and stratified bootstrap | yes | no | yes |
| Zero-allocation strata; bootstrap lacks FPC and rescaling | yes | no | yes |
| Snapshot build must refuse incomplete shards and reconcile every ID | yes | no | yes |
| Repo public from Wave 0 conflicts with spec section 9 | no | yes | yes |
| Site, release tooling over-built before any finding | yes | yes | yes |
| Site contract lacks fields; production could ship fixtures | yes | yes | yes |
| Parallel `uv add` conflicts; CLI registry crash; Task 0.1 git sequence fails | no | yes | yes |

## Accepted fixes (auto-decided; applied to the plans after the gate)

Wave 0:
1. Task 0.1 uses `git commit-tree` on an empty tree, run in a worktree while the walk runs.
2. Task 0.2 adds every dependency (optional groups: snapshot, label, dev) and all
   `tests/<lane>/__init__.py`; lanes never touch `pyproject.toml` or `uv.lock`.
3. Contracts add `COVERAGE`, `paths.SAMPLES`, `sample_path()`, `ledger_path()`; paths are
   read at call time; `acquire.snapshot_dir` renamed `raw_dir`.
4. Registry skips a missing parent package, and lanes import heavy deps inside handlers.
5. Secret preview prints rule, path, line only; the hook scans staged blobs
   (`git show :path`, `-z`, ACMR); a pre-push gitleaks hook; gitleaks pinned by checksum
   and run first in CI; private-key test literals built at runtime.
6. `.gitignore` anchors `/data/`, `/runs/`, `/exports/` and ignores
   `**/.observablehq/cache/`.
7. AGENTS.md carries the command and flag table, dependency rule, test layout, network
   ban, mock usage, stop rules. `atlas timeline mark <event>` added for time-to-finding.
8. A redacted response-shape fixture from the 2026-09-28 smoke run is committed for L3.

Lanes:
9. L1: build refuses unless all shards are complete; coverage reconciles every scanned ID
   from shard metas; disk guard; `_parts` cleaned at start; verify never crashes on a bad
   file; numpy parent resolution; normalize and language detection per shard in a process
   pool; `text_html` dropped from `comments.parquet` (raw shards keep it); lingua limited
   to common languages, code and URLs stripped first, exclude only when English
   confidence is below 0.2; shared `load_items` lives in L1.
10. L2: every stratum gets at least 2 units or is collapsed; assert weights sum to N;
    bootstrap with Rao-Wu rescaling and finite-population correction (census interval is
    zero); `domain=` mask; `draw_from_snapshot` shared by L4 and L7.
11. L3: attempt-level reserve and settle; cumulative spend across all runs of a budget
    name; worst case = max(8000, 2 x estimate); 429 is not charged; schema errors retry
    once; model mismatch aborts; answers flushed atomically before `done`; parts never
    overwritten; manifest lists question sets; `summarize(by="question_set")`; items
    accepted as an iterable; `jev smoke --set deep` preflight.
12. L4: calibration queue drawn from the pilot sample in frozen score bands with stored
    rates, stop rule of at least 40 positives, 10% blind repeats, `domain` labeled on 50
    items; Hansel approves the rubric first; `nanpercentile` with `n_undefined`; stratified
    bootstrap; threshold picked on the recall lower bound; `evaluate` fails under 95% join.
13. L5 (trimmed for M1 to M2): allowlist, stage, Parquet-aware scan, text-column gate,
    claims check with qualifier and interval fields. Restore over HTTPS and rehydrate
    reuse `hn_api`, and move to plan 2.
14. L7: 20 synthetic injected-instruction cases reported separately; deep token cost
    projected from screen positives; report folds in calibration results.
15. Master 2.1 and 2.2 commands corrected (`--snapshot`, `--from-sample`, `--question`).
16. Taxonomy provenance stores comment IDs and hashes only.
17. Month strata: 12 window-relative periods (P01 to P12), displayed as date ranges.

Plan-2 deferred list adds: `atlas replay` and `atlas site build`, a 10-minute
stranger-replay CI test, held-out exclusion of pilot, calibration and taxonomy IDs, a
reply-solution noul ("does a reply name an existing tool"), finding-card fields for
existing solutions and max thread share, RPM token bucket, Findings-first site with claim
anchors, in-chart footers, Open Graph cards, mobile budget, accessible chart tables.

## Decisions for Hansel (final gate)

See the session: repo visibility timing, scope reorder (one-finding spike, trimmed
L5 and L6), human labeling time, and key rotation before the lanes start.

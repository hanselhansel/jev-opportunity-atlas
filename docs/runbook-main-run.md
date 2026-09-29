# Runbook: the main run, replayable

The exact command sequence of the 2026-09-29/30 main run, in order, with each
command's budget, run ID, and expected output. Every paid command prints its
estimate first and dispatches nothing until `--yes` is given. Run IDs that the
session already produced are shown exactly; IDs for the stages after the
screen follow the session's `main-*` convention.

Prerequisites: `uv sync`, a real `TYPESAFE_API_KEY` in the environment (or the
configured key source), and the raw HN pull in `data/raw/` (`atlas acquire`
over the snapshot window; free, but days long). Nothing below needs HN text in
this repo, and no key is ever written to a file.

## IDs at a glance

| Artifact | ID | Budget | Cap |
|---|---|---|---|
| Snapshot | `hn-2025-09-28_2026-09-28-v1` | none | - |
| Token measurement | `measure-*` | smoke | $0.01 |
| Pilot sample and run | `pilot-20260929` | pilot | $0.50 |
| Packed pilot | `pilot-20260929-packed` | pilot | |
| Packed calibration | `pilot-20260929-packedcal` | pilot | |
| Injected cases | `pilot-20260929-injected` | pilot | |
| Pilot card runs | `pilot-20260929-cards`, `pilot-20260929-cards-t1` | pilot | |
| Pilot planted checks | `pilot-20260929-planted`, `pilot-20260929-planted-v2` | pilot | |
| Main sample (superseded) | `main-20260930` | free | - |
| Main sample (used) | `main-20260930b` | free | - |
| Main screen | `main-screen-20260930` | screen | $8.00 |
| Facet sample and run | `main-facets-20260930` | facets | $2.50 |
| Card assignment | `main-cards-*` | assign | $2.50 |
| Merge, verify, planted | `main-merge-*`, `main-verify-*`, `main-planted-*` | merge_verify | $0.60 |
| Synthetic benchmark | `bench-*` | discovery | $1.00 |

## 1. Snapshot (free)

```bash
uv run atlas snapshot build   # reads configs/acquisition.toml
uv run atlas snapshot verify  # table hashes and schemas
```

Writes `data/snapshots/hn-2025-09-28_2026-09-28-v1/` (comments, stories,
context, coverage) and `manifests/snapshots/hn-2025-09-28_2026-09-28-v1.json`.
`verify` prints one line per check and a final ok/fail.

## 2. Token measurement (smoke)

```bash
uv run atlas jev measure --sets screen@1,facets@1 --yes
```

Three fully synthetic comments (1, 4, and 16 sentences) through the real
runner under budget `smoke`; run ID `measure-<UTC timestamp>`. Prints the
plan JSON, one progress line per set, then the token table:

```text
set           short  medium    long
screen@1        ...      ...     ...
facets@1        ...      ...     ...
run measure-... calculated_usd ... unknown 0 attempts 6
```

Results are recorded in `docs/measurements/2026-09-28-token-costs.md`; they
set the per-question prices every later estimate uses.

## 3. Pilot (budget `pilot`, cap $0.50)

```bash
uv run atlas pilot draw --seed 20260929                          # free
uv run atlas pilot screen --sample pilot-20260929 --run pilot-20260929 --yes
uv run atlas pilot facets --run pilot-20260929 --yes
uv run atlas pilot packed --run pilot-20260929 --yes             # -> pilot-20260929-packed
uv run atlas pilot injected --run pilot-20260929 --yes           # -> pilot-20260929-injected
uv run atlas pilot gold --run pilot-20260929 --sample pilot-20260929
uv run atlas pilot report --run pilot-20260929                   # -> runs/pilot-20260929/pilot_report.md
```

`draw` writes `data/samples/pilot-20260929.{parquet,json}`. Every paid stage
prints an estimate JSON (`calls`, `input_tokens`, `usd`, `cap_usd`,
`remaining_usd`) and a run summary with `completed`, `failed`,
`skipped_completed`, `cache_hits`, `new_requests`, `wall_s`, `stopped`.
`gold` writes the calibration and audit label queues under
`data/labels/queues/` plus `data/labels/gold_draws.parquet`; Hansel labels
them in the labeler (`atlas label run`), which is human time, not Jev spend.
The pilot's card gate (design section 9) ran `cards assign` twice (cardset
`pilot`, versions `t0` then `t1`) and `cards planted` twice (`planted.v1`,
`planted.v2`) under the pilot budget.

```bash
uv run atlas pilot packed-cal --run pilot-20260929 --yes         # -> pilot-20260929-packedcal
```

Packed screen over the calibration-queue ids that `pilot-20260929-packed` did
not cover, so packed and single answers can both be scored on the same blind
labels. Prints `calibration ids N, already packed M, to pack K`, then the
estimate; on `--yes` writes the long-format packed map
(`packed_id, slot, comment_id`) and dispatches under `pilot`.

## 4. Main draw (free)

```bash
# Superseded: kept for audit, never screened.
uv run atlas sample draw-pooled --pilot-run pilot-20260929 \
    --budget-usd 7.50 --cost-scale 0.424 --seed 20260930 \
    --sample-id main-20260930

# Used draw.
uv run atlas sample draw-pooled --pilot-run pilot-20260929 \
    --budget-usd 6.64 --cost-scale 0.424 --seed 20260930 \
    --sample-id main-20260930b
```

Pools the pilot's firsthand rates (at `firsthand_problem >= 0.7`) and
per-comment screen costs across the two half-years, allocates on pooled
strata with the 2% floor, then splits each pooled allocation across H1/H2
proportional to N so both halves keep one sampling rate. `cost-scale 0.424`
is the measured packed/single tokens-per-comment ratio. Prints `n`, the H1/H2
split, expected positives, expected tokens against the token budget, and the
largest weight, then writes the sample plus a design manifest.

Why `main-20260930` was superseded: the $7.50 allocation targeted the $8.00
screen cap, but a probe of the first draw showed real packed calls cost
1.115x the allocation model, so $7.50 aimed at about $8.36 real. The redraw
at $6.64 targets about $7.40 real, inside the cap.

## 5. Main screen (budget `screen`, cap $8.00)

```bash
uv run atlas screen run --sample main-20260930b --run main-screen-20260930 --yes
uv run atlas screen table --run main-screen-20260930
```

`screen run` packs k=5 comments per call at 1,000 requests/minute in 5,000-
comment chunks; 605,125 comments is about 121k calls. It resumes from
`done.jsonl` after any interrupt. `screen table` writes
`runs/main-screen-20260930/screen_by_comment.parquet`
(`comment_id, story_id, stratum, half, weight, firsthand_p`).

## 6. Two-phase facets (budget `facets`, cap $2.50)

```bash
uv run atlas facets draw --screen-run main-screen-20260930 \
    --sample-id main-facets-20260930 --seed 20260931
uv run atlas facets estimate --sample-id main-facets-20260930
uv run atlas facets run --sample-id main-facets-20260930 \
    --run main-facets-20260930 --yes
```

Draws, within each v2 stratum of the screen table: positives
(`firsthand_p >= 0.7`), 28,000 total, and a 2,000-comment below-cutoff check
sample, each stratum's `n2_h` proportional to its phase-1 weighted count.
Every row keeps `w1` and `p2`; final weight is `w1 / p2`. `draw` prints
`drew N (P pos, M neg)`; `estimate` prints the probe-extrapolated cost JSON.
`run` sends `facets@2` in chunks at 1,000 rpm, prints one `chunk i: {...}`
summary per chunk, and resumes after an interrupt.

## 7. Cards (budgets `assign` $2.50, `merge_verify` $0.60)

Card text is written by Claude and approved by Hansel; the cardset YAML lives
under `configs/cards/`. The assign items parquet (`comment_id`,
`pain_sentence`, `sentences`) is built from the facets@2 `pain_sentence`
answers joined to the snapshot.

```bash
uv run atlas cards assign --cardset <name> --version <t> \
    --run main-cards-<t> --budget assign --items <items.parquet> --yes
uv run atlas cards merge --cardset <name> --version <t> \
    --run main-merge-<t> --budget merge_verify --yes
uv run atlas cards verify --cardset <name> --version <t> \
    --run main-verify-<t> --budget merge_verify --yes
uv run atlas cards planted --cardset <name> --version <t> \
    --run main-planted-<t> --planted v1 --budget merge_verify --yes
```

`assign` prints the token estimate then per-batch progress; `verify` fills
`verified_p` on the assignment rows; `planted` reports how many planted
synthetic comments landed on the right card (pre-registered bar: >= 90%).

## 8. Synthetic benchmark (budget `discovery`, cap $1.00)

```bash
uv run atlas benchmark run --run bench-<date> --budget discovery --yes
uv run atlas benchmark report --run bench-<date>
```

Runs the invented cases in `configs/benchmark/cases.v1.yaml` through the
pipeline and scores them; the report lands in the run directory.

## 9. Site data and X charts (free)

```bash
uv run atlas site data --screen-run main-screen-20260930 \
    --facets-run main-facets-20260930 --assign-run <assign-run> \
    --taxonomy <t>
uv run atlas x charts --data site/data-real
```

`site data` writes every table in `SITE_TABLES` under `site/data-real/` with
`meta.mode == "real"` (parquet, no comment text). `x charts` renders the
1600x900 PNGs to `exports/x/<date>/` with the caveat footer baked in.

## 10. Release (free, local)

```bash
uv run atlas release pack --release <tag> --site-data site/data-real
uv run atlas site build --data site/data-real --base /jev-opportunity-atlas/
uv run atlas release pages --dist site/dist --push   # --push: main session only
```

`pack` writes `site-<tag>.tar.zst`, `full-<tag>.tar.zst`, and
`assets-<tag>.json` under `exports/<tag>-assets/`; `pages` builds the
gh-pages commit (dry run without `--push`). Neither bundle contains comment
text or usernames; see `docs/reproduce.md` for the verifier side.

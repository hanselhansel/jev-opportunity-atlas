# Reproduce the atlas

You can check every published number without an API key, without gh auth, and
without calling Hacker News. A public release has two bundles on its GitHub
Release page:

| Bundle | Contents | Size |
|---|---|---|
| `site-<tag>.tar.zst` | site tables, manifests, claims ledger, configs, snapshot manifest and coverage | tens of MB |
| `full-<tag>.tar.zst` | Jev answers, ledgers, samples, labels, comment ids and text hashes | larger; may be split into `.partNNN` assets |

`assets-<tag>.json` lists every asset with its SHA-256. Restore downloads each asset
over plain HTTPS, checks its hash before unpacking, rejects unsafe paths, then checks
every line of `SHA256SUMS` and the release `schema_version`. Nothing lands in
`data/releases/<tag>` unless all of that passes.

Neither bundle contains comment text or usernames. Comments stay their authors';
tier 3 shows how to refetch them from the official API.

You need `git` and [uv](https://docs.astral.sh/uv/). Tier 2 also needs Node 20+.
Replace `<tag>` with a release tag from the Releases page.

## Tier 1: claims only (about 5 minutes)

```bash
git clone https://github.com/hanselhansel/jev-opportunity-atlas
cd jev-opportunity-atlas
uv sync --no-default-groups
uv run --no-sync atlas release restore --release <tag>
uv run --no-sync atlas release replay --release-dir data/releases/<tag>
```

Expected output. `release restore` prints its report:

```text
{
  "ok": true,
  "bad": [],
  "missing": [],
  "extra": [],
  "schema_version": 1,
  "bundles": [
    "site"
  ],
  "release_dir": "<clone>/data/releases/<tag>"
}
```

`release replay` makes no network calls. It prints one line per claim in
`claims/claims.yaml`:

```text
verify: ok (schema_version 1)
claim <claim id>: pass
...
claims: <n> checked
site data: data/releases/<tag>-site-data
replay: ok
```

A drifted claim prints `claim <id>: fail (actual <x> vs expected <y>)`, then
`replay: FAIL`, and exits 1. A tampered file prints `verify: FAIL bad=[...]` and
stops before any claim runs.

## Tier 2: the site (about 10 minutes)

```bash
scripts/replay.sh <tag>
```

The script runs `uv sync --no-default-groups`, restores the site bundle (or reuses
`data/releases/<tag>` if it is already there), runs `release replay`, then, when
`node` is installed, runs `npm ci` and a production build in `site/`. Expected
output ends with:

```text
verify: ok (schema_version 1)
claim <claim id>: pass
...
replay: ok
...
site: built into site/dist
replay: done in <seconds>s
```

Open the result with `python3 -m http.server -d site/dist 8000` and visit http://localhost:8000. The
production build refuses data whose `meta.mode` is not `real`, so a fictional
fixture can never pass for a finding.

## Tier 3: full re-analysis from saved answers

Restore both bundles into a fresh directory:

```bash
uv sync --no-default-groups
uv run --no-sync atlas release restore --release <tag> --bundle site --bundle full --dest data/releases-full
uv run --no-sync atlas release replay --release-dir data/releases-full/<tag>
```

Expected output matches tier 1, with `"bundles": ["site", "full"]` in the restore
report. With the full bundle present, claims whose SQL reads
`runs/<run_id>/answers/*.parquet` recompute from the saved Jev answers instead of
failing for missing files. Large files split at release time are joined back
together and checked slice by slice against their recorded hashes.

The saved answers, ledgers, samples, and labels are then under
`data/releases-full/<tag>/`. Every chart replays from them with no Jev calls; the
site-data builder (`uv run atlas site data --help`) rebuilds the site tables from
those runs.

### Optional: refetch comment text

This step calls the official HN API (`hacker-news.firebaseio.com`), one request
per comment:

```bash
uv run --no-sync atlas release rehydrate --release-dir data/releases-full/<tag> --limit 1000
```

It prints a summary such as:

```text
{
  "release": "<tag>",
  "source": "snapshot/comments_public.parquet",
  "n": 1000,
  "summary": {"match": <n>, "changed": <n>, "missing": <n>},
  "no_longer_matching_share": <share>,
  "out_dir": "data/rehydrated/<tag>"
}
```

`match` means the current text hashes to the published `text_sha256`. `changed`
means the comment was edited after the snapshot. `missing` means it is deleted,
dead, or gone. Text is written only to `data/rehydrated/<tag>/`, which git ignores.

## Publish the essay

The interactive essay in `essay/` goes through the same guarded `gh-pages`
path as the site. Both commands are local; nothing here publishes.

```bash
uv run --no-sync atlas story dist --out essay-dist
uv run --no-sync atlas release pages --dist essay-dist --kind essay
```

`story dist` copies the publishable files (`index.html`, `app.js`,
`style.css`, `charts/`, `lib/`, `content/story.md`, `data/story.json`; tests
and fixtures stay behind), runs `story check` on the copied `story.json`,
and applies a privacy gate: no URLs outside `index.html`'s cdn.jsdelivr.net
importmap, no email addresses, no local absolute paths, no secrets.

`release pages --kind essay` is a dry run. It re-checks the dist, builds an
orphan `gh-pages` commit with a `.nojekyll` file in a temporary worktree,
scans it, and prints the commit it would push. The push itself is a
separate, human-approved step: rerun with `--push` in the main session only.

# Agent rules for jev-opportunity-atlas

Read this before any change. The approved design is
`docs/superpowers/specs/2026-09-29-jev-opportunity-atlas-design.md`. Lane plans live in
`docs/superpowers/plans/`. A lane plan's **Amendments** section overrides earlier text in
the same plan.

## Hard rules

1. **Secrets.** Never read macOS Keychain. Never set a real `TYPESAFE_API_KEY`. Tests use
   the canary built at runtime: `"apikey_" + "0" * 36 + "_" + "f" * 64`. Never write any
   key-shaped literal into a file.
2. **Network.** Tests never call `api.typesafe.ai`, `hacker-news.firebaseio.com`, or
   `hn.algolia.com`. Use `httpx.MockTransport` or the `FakeClient` pattern in
   `tests/test_acquisition.py`.
3. **No GitHub Actions.** This project has no CI workflows. Do not add
   `.github/workflows/`. Verification is local: `scripts/verify.sh`.
4. **Dependencies.** Never run `uv add` or edit `pyproject.toml` or `uv.lock`. Every
   dependency is already installed (`uv sync`). If you truly need a new one, stop and
   report.
5. **Frozen files.** Do not edit `src/atlas/contracts.py`, `src/atlas/paths.py`,
   `src/atlas/cli.py`, `tests/__init__.py`, or any `tests/<lane>/__init__.py`. If a
   contract is wrong, stop and report.
6. **Scope.** Touch only the files your lane plan lists. Do not widen scope.
7. **Hooks.** Never use `git commit --no-verify` or `git push --no-verify`. If a hook
   blocks you, fix the cause.
8. **HN text and usernames** never go into tracked files, fixtures that look real, or
   exports. Synthetic fixtures use IDs of 9,000,000,000 and above.

## How to work

- TDD: write the test from the plan, run it and see it fail, implement, see it pass.
- Commit after each green task and push after every commit.
- Import heavy optional dependencies (lingua, streamlit) inside the function that needs
  them, never at module top.
- Access paths as `from atlas import paths` then `paths.X` at call time, so tests can
  monkeypatch them.
- Keep every source file under 400 lines; split before it grows past that.
- Register CLI commands through your module's `register(subparsers)`; the module name is
  already listed in `atlas.cli.COMMAND_MODULES`.

## Commands and flags (frozen)

| Command | Owner |
|---|---|
| `acquire`, `coverage` | existing |
| `snapshot build`, `snapshot verify` | L1 |
| `sample draw`, `sample expand`, `sample show` | L2 |
| `jev smoke`, `jev ledger` | L3 |
| `label run`, `eval run` | L4 |
| `release stage`, `release check`, `claims check` | L5 |
| `site build`, `site preview` | L6 |
| `pilot draw`, `pilot screen`, `pilot facets`, `pilot packed`, `pilot injected`, `pilot gold`, `pilot report` | L7 |
| `discover search` | L8 |
| `benchmark run`, `benchmark report` | L18 |
| `screen run`, `screen table` | L17 |
| `site data`, `x charts` | L20 |
| `release pack`, `release restore`, `release rehydrate`, `release replay`, `release pages` | L21 |
| `robust subsample-screen`, `robust subsample-items`, `robust assign-paraphrase`, `robust compare-screen`, `robust compare-assign` | L25 |
| `builders draw`, `builders run` | S6 |
| `sample draw-pooled` | L22 |
| `facets draw`, `facets estimate`, `facets run` | L22 |
| `facets expand` | L27 |
| `pilot packed-cal` | L22 |
| `jev measure` | L22 |
| `story data`, `story check` | S1 |
| `story dist`, `release pages --kind essay` | S9 |
| `cards items`, `cards draft-sample`, `cards replies` | L23 |
| `cards induce` | L26 |
| `cards combine` | L28 |
| `solutions run` | S5 |
| `timeline mark` | existing |

Common flags: `--snapshot` (default: `snapshot_id` in `configs/acquisition.toml`),
`--run`, `--sample`, `--label-set`, `--budget`. If a lane plan names a command
differently, this table wins.

## Tests

- Lane tests live in `tests/<lane>/` (sources, sampling, inference, evaluation,
  publication, sitedata, discovery, pilot). Shared helpers import as
  `tests.<lane>.<module>`.
- Use `Path(__file__).resolve().parents[N]` for repo paths, never the current directory.

## Before you open a PR

```bash
scripts/verify.sh          # gitleaks, ruff, pytest; must print "verify: ok"
gh pr create --base main --fill
```

Final message: the PR URL and the pytest summary line. If blocked, stop and say exactly
what blocks you.

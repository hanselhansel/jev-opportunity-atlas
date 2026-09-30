# S8c: Word-like tool names match case-sensitively

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Read `docs/superpowers/plans/2026-09-30-story-master.md` and `docs/superpowers/plans/2026-09-30-story-S5-tools.md` first.

Branch: feat/s8c-tool-names

**Goal:**
- `match.find_mentions` also matches each tool's `name`, case-insensitively. Names that are common English words therefore flood the "named in complaints" tallies. On real data, "Wise" got 90 complaint threads from the word "wise", and "Signal" got 154.
- Add a per-tool flag so such names match only case-sensitively. Aliases keep their current rules.

**Files you own:**
- `src/atlas/solutions/match.py`
- `configs/tools.v1.yaml`
- `tests/solutions/test_match.py`

## Task 1
- [ ] **Test** `test_name_case_flag`:
  - a tool `{name: Wise, aliases: [wise.com], category: saas_business, name_case: true}` does not match "that was wise";
  - it does match "I used Wise to pay";
  - it matches "wise.com" through its alias.
- [ ] **Test** `test_default_name_still_case_insensitive`: a tool without the flag keeps today's behavior.
- [ ] Implement `name_case` (default false) in `load_tools` and `find_mentions`.
- [ ] In `configs/tools.v1.yaml`, set `name_case: true` on tools whose name is a common English word:
  - Wise, Signal, Spring, Slack, Zoom, Linear, Notion, Medium, Arc, Bolt, Amp, Kiro, Unity, Ring, Nest, Stripe, Plaid, Epic, Oracle, Discord, Matrix, Steam, Render, Railway, Warp, Caddy, Zed, Swift, Rust, Go, Ruby, Spring, Obsidian, Canva, Sentry, Postman, Bun, Deno, Yarn, Poetry, Cargo, Nix, Proton, Kagi, Arc, Pixel, Galaxy, Dell, Anker, Garmin, Kindle, Kobo, Boox, Roku, Sonos, Tesla, Uber, Wise, Revolut, Workday, Greenhouse, Okta, Twilio, Calendly, Airtable, Zapier, Flock, Palantir, Chrome, Safari, Brave, Edge;
  - skip any name not present in the file.
- [ ] Add a test that loads the real `configs/tools.v1.yaml` and asserts `Wise` and `Signal` have `name_case: true`.
- [ ] `scripts/verify.sh` prints `verify: ok`. Open the PR. Final message: PR URL and pytest summary line.

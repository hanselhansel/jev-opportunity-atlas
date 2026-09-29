#!/bin/sh
# Local verification gate: lint, tests, and a full-history secret scan.
# Run before every merge and on every push (the pre-push hook calls this).
set -e
cd "$(git rev-parse --show-toplevel)"
command -v gitleaks >/dev/null || { echo "gitleaks is required: brew install gitleaks"; exit 1; }
gitleaks git --log-opts=HEAD --config .gitleaks.toml --redact --no-banner --log-level warn .
uv run --quiet ruff check src tests
uv run --quiet pytest -q
# Tests that run git inside hooks once flipped the shared repo to bare; fail loudly if so.
if [ "$(git config --get core.bare)" = "true" ]; then echo "verify: FAILED, a test set core.bare=true in the shared repo config"; git config core.bare false; exit 1; fi
echo "verify: ok"

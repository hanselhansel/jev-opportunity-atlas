#!/bin/sh
# Local verification gate: lint, tests, and a full-history secret scan.
# Run before every merge and on every push (the pre-push hook calls this).
set -e
cd "$(git rev-parse --show-toplevel)"
command -v gitleaks >/dev/null || { echo "gitleaks is required: brew install gitleaks"; exit 1; }
gitleaks git --log-opts=HEAD --config .gitleaks.toml --redact --no-banner --log-level warn .
uv run --quiet ruff check src tests
uv run --quiet pytest -q
echo "verify: ok"

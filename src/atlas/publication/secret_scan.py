"""Secret scanner used by the pre-commit hook, `scripts/verify.sh`, and release staging.

A finding is rule, path, and line number only. It never carries any part of the
matched text, so hook output, logs, and errors are safe to show anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

RULES = {
    "typesafe-api-key": re.compile(
        r"(?i)apikey(?:_|%5f)[0-9a-f]{36}(?:_|%5f)[0-9a-f]{64}"
    ),
    "github-token": re.compile(
        r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}"
    ),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private-key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{30,}"),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int

    def __str__(self) -> str:
        return f"SECRET {self.rule} {self.path}:{self.line}"


def scan_text(text: str, path: str) -> list[Finding]:
    hits = []
    for n, line in enumerate(text.splitlines(), start=1):
        for rule, rx in RULES.items():
            hits.extend(Finding(rule, path, n) for _ in rx.finditer(line))
    return hits


def scan_paths(paths: list[Path]) -> list[Finding]:
    hits = []
    for p in paths:
        try:
            text = Path(p).read_text(errors="ignore")
        except (IsADirectoryError, FileNotFoundError):
            continue
        hits.extend(scan_text(text, str(p)))
    return hits

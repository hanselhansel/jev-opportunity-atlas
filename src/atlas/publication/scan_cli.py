"""`python -m atlas.publication.scan_cli --staged | paths...`: exit 1 on any finding.

`--staged` scans the staged blob of every added, copied, modified, or renamed file
(what will actually be committed), not the working-tree copy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from atlas.publication.secret_scan import scan_paths, scan_text


def staged_findings() -> list:
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    hits = []
    for raw in names:
        if not raw:
            continue
        name = raw.decode("utf-8", errors="replace")
        blob = subprocess.run(
            ["git", "show", f":{name}"], capture_output=True, check=True
        ).stdout
        hits.extend(scan_text(blob.decode("utf-8", errors="ignore"), name))
    return hits


def main(argv: list[str]) -> int:
    hits = (
        staged_findings()
        if argv[:1] == ["--staged"]
        else scan_paths([Path(p) for p in argv])
    )
    for h in hits:
        print(h, file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

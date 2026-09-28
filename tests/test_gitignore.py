import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def ignored(path: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", path]
        ).returncode
        == 0
    )


@pytest.mark.parametrize(
    "path",
    [
        "data/raw/x.jsonl.zst",
        "runs/r1/ledger.jsonl",
        "exports/v1/SHA256SUMS",
        ".env",
        ".env.local",
        "site/src/.observablehq/cache/data/x.parquet",
        "site/fixtures/meta.parquet",
        "site/dist/index.html",
    ],
)
def test_private_or_generated_paths_are_ignored(path):
    assert ignored(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "site/src/data/meta.parquet.py",
        "src/atlas/publication/secret_scan.py",
        "tests/test_secret_scan.py",
        "configs/budgets.toml",
    ],
)
def test_tracked_sources_are_not_ignored(path):
    assert not ignored(path)

"""Repository-relative locations. Everything under data/, runs/, exports/ is gitignored.

Read these as `paths.X` at call time (never `from atlas.paths import X`) so tests can
monkeypatch them.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
SNAPSHOTS = DATA / "snapshots"
SAMPLES = DATA / "samples"
LABELS = DATA / "labels"
CACHE = DATA / "cache"
DISCOVERY = DATA / "discovery"
RUNS = ROOT / "runs"
EXPORTS = ROOT / "exports"
MANIFESTS = ROOT / "manifests"
CONFIGS = ROOT / "configs"


def snapshot_dir(snapshot_id: str) -> Path:
    return SNAPSHOTS / snapshot_id


def sample_path(sample_id: str) -> Path:
    return SAMPLES / f"{sample_id}.parquet"


def run_dir(run_id: str) -> Path:
    return RUNS / run_id


def ledger_path(run_id: str) -> Path:
    return RUNS / run_id / "ledger.jsonl"

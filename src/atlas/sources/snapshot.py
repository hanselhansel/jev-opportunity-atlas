"""Build and verify a canonical snapshot: contract Parquet tables + manifest.

`build` turns the raw acquisition shards into comments/stories/context/coverage
parquet under `paths.snapshot_dir(cfg["snapshot_id"])`. It refuses to run on
incomplete shards or low disk, fetches missing thread ancestors when a
`fetch_context_fn` is supplied, and writes a hashed `manifest.json`.
`verify` recomputes file hashes, row counts, and schemas; it never raises.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from atlas import contracts, paths
from atlas.sources import acquire
from atlas.sources import shards as sh
from atlas.sources.snapshot_passes import (
    context_rows,
    run_pass1,
    run_pass2,
    write_context_part,
)


class SnapshotError(Exception):
    """Refusal to build: incomplete input, low disk, or failed reconciliation."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _code_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=paths.ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _check_shards(shard_dir: Path, specs: list) -> None:
    status = Counter(sh.shard_status(shard_dir, s) for s in specs)
    bad = {k: status[k] for k in ("missing", "partial", "corrupt") if status[k]}
    if bad:
        desc = ", ".join(f"{n} {k}" for k, n in sorted(bad.items()))
        raise SnapshotError(
            f"refusing to build: {desc} shard(s); "
            "finish acquisition first with `uv run atlas acquire --workers 3`"
        )


def _disk_guard(sdir: Path, raw_bytes: int) -> None:
    anchor = sdir
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    need = 3 * raw_bytes + 2 * 2**30
    free = shutil.disk_usage(anchor).free
    if free < need:
        raise SnapshotError(
            f"disk guard: need ~{need / 2**30:.1f} GiB, free "
            f"{free / 2**30:.1f} GiB at {anchor}"
        )


def _meta_totals(shard_dir: Path, specs: list) -> tuple[dict, int]:
    """Sum shard meta states/types; return ({'state':..,'type':..}, n_lines)."""
    states: Counter = Counter()
    types: Counter = Counter()
    n_lines = 0
    for spec in specs:
        meta = json.loads(sh.paths(shard_dir, spec)[1].read_text())
        states.update(meta["states"])
        types.update(meta["types"])
        n_lines += meta["n_lines"]
    return {"state": dict(states), "type": dict(types)}, n_lines


def build(
    cfg: dict,
    root: Path,
    fetch_context_fn=None,
    workers: int | None = None,
) -> dict:
    """Build the snapshot tables and manifest; returns the manifest dict."""
    import duckdb

    from atlas.sources.snapshot_tables import write_tables

    sdir = paths.snapshot_dir(cfg["snapshot_id"])
    raw = acquire.raw_dir(root, cfg)
    bpath = raw / "boundaries.json"
    if not bpath.exists():
        raise SnapshotError(f"missing boundaries.json under {raw}")
    b = json.loads(bpath.read_text())
    ws, we = acquire.ts(b["window_start"]), acquire.ts(b["window_end"])
    shard_dir = raw / "shards"
    specs = sh.plan_shards(
        b["scan_first_id"], b["scan_last_id"], cfg["shard_size"]
    )
    _check_shards(shard_dir, specs)

    parts_dir = sdir / "_parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    raw_bytes = sum(sh.paths(shard_dir, s)[0].stat().st_size for s in specs)
    _disk_guard(sdir, raw_bytes)
    sdir.mkdir(parents=True, exist_ok=True)

    meta_totals, ids_scanned = _meta_totals(shard_dir, specs)

    # Pass 1: shards -> normalized parts.
    part_paths, tally = run_pass1(shard_dir, specs, parts_dir, ws, we, workers)
    recon = {k: tally[k] for k in ("comments", "stories", "other_types",
                                  "null", "failed", "deleted_without_type")}
    recon["ids_scanned"] = ids_scanned
    if sum(v for k, v in recon.items() if k != "ids_scanned") != ids_scanned:
        raise SnapshotError(
            f"reconciliation failed: {recon} does not cover {ids_scanned} ids"
        )

    # Pass 2: resolve roots over scan ids plus existing context, then fetch
    # whatever is still missing and resolve once more.
    context_dir = raw / "context"
    ctx_rows = context_rows(context_dir, ws, we)
    roots_path = parts_dir / "roots.parquet"
    missing, _unresolved = run_pass2(part_paths, ctx_rows, roots_path)
    if fetch_context_fn is not None and len(missing):
        fetch_context_fn({int(i) for i in missing}, context_dir)
        ctx_rows = context_rows(context_dir, ws, we)
        missing, _unresolved = run_pass2(part_paths, ctx_rows, roots_path)
    ctx_part = write_context_part(ctx_rows, parts_dir / "ctx.parquet")

    # Pass 3: joins, eligibility, contract tables.
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    try:
        stats = write_tables(
            con, part_paths, ctx_part, roots_path, sdir, ws, we,
            len(missing), meta_totals,
        )
    finally:
        con.close()

    files = {}
    for name in (
        "comments.parquet",
        "stories.parquet",
        "context.parquet",
        "coverage.parquet",
    ):
        p = sdir / name
        files[name] = {
            "sha256": _sha256(p),
            "bytes": p.stat().st_size,
            "rows": pq_rows(p),
        }

    shutil.rmtree(parts_dir)
    manifest = {
        "schema_version": contracts.SCHEMA_VERSION,
        "snapshot_id": cfg["snapshot_id"],
        "window": {"start": b["window_start"], "end": b["window_end"]},
        "boundaries": b,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_commit": _code_commit(),
        "counts": {
            "items": tally["comments"] + tally["stories"]
            + tally["other_types"] + tally["deleted_without_type"],
            "comments": stats["comments"],
            "stories": stats["stories"],
            "context": stats["context"],
            "eligible": stats["eligible"],
            "exclusion_reasons": stats["reasons"],
        },
        "reconciliation": recon,
        "files": files,
    }
    (sdir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    )
    return manifest


def pq_rows(path: Path) -> int:
    import pyarrow.parquet as pq

    return pq.ParquetFile(path).metadata.num_rows


_CONTRACTS = {
    "comments.parquet": contracts.COMMENTS,
    "stories.parquet": contracts.STORIES,
    "context.parquet": contracts.CONTEXT,
    "coverage.parquet": contracts.COVERAGE,
}


def _physical_schema(contract: pa.Schema) -> pa.Schema:
    """Contract schema as it must appear in the Parquet physical layer.

    Parquet has no seconds timestamp unit; writers coerce timestamp[s] to
    milliseconds. Contract timestamps therefore compare as ms.
    """
    return pa.schema(
        [
            f.with_type(pa.timestamp("ms", tz="UTC"))
            if pa.types.is_timestamp(f.type)
            else f
            for f in contract
        ]
    )


def verify(sdir: Path) -> dict:
    """Recompute hashes, row counts, and schemas. Never raises."""
    report = {"ok": True, "bad_files": [], "schema_errors": []}
    sdir = Path(sdir)
    mpath = sdir / "manifest.json"
    if not mpath.exists():
        report["ok"] = False
        report["schema_errors"].append("manifest.json missing")
        return report
    try:
        manifest = json.loads(mpath.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        report["ok"] = False
        report["schema_errors"].append(f"manifest.json unreadable: {exc}")
        return report

    import pyarrow.parquet as pq

    for name in sorted(manifest.get("files", {})):
        info = manifest["files"][name]
        p = sdir / name
        if (
            not p.exists()
            or p.stat().st_size != info.get("bytes")
            or _sha256(p) != info.get("sha256")
        ):
            report["bad_files"].append(name)
            continue
        try:
            pf = pq.ParquetFile(p)
            if pf.metadata.num_rows != info.get("rows"):
                report["bad_files"].append(name)
                continue
            if not pf.schema_arrow.equals(
                _physical_schema(_CONTRACTS.get(name))
            ):
                report["schema_errors"].append(name)
        except Exception:  # noqa: BLE001 - verify reports, never raises
            report["bad_files"].append(name)
    report["bad_files"].sort()
    report["schema_errors"].sort()
    report["ok"] = not report["bad_files"] and not report["schema_errors"]
    return report

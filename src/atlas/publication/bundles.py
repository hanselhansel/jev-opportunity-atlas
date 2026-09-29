"""Release bundle layout: which files go in which bundle, verification, chunk
reassembly, adding site tables, and packing.

A staged release (exports/<tag>) packs into two bundles:

- `site-<tag>.tar.zst`: site tables, manifests, claims, configs, and the snapshot
  manifest and coverage. Small; enough to check claims and build the site.
- `full-<tag>.tar.zst`: everything else (answers, ledgers, samples, labels, ids).

Both carry `release_manifest.json` and `SHA256SUMS`. `assets-<tag>.json` lists every
asset with its sha256, so each download is checked before anything unpacks.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from pathlib import Path

from atlas import contracts
from atlas.publication.allowlist import scan_release, text_gate
from atlas.publication.export import _sha256_file, chunk_large_files

META_FILES = ("release_manifest.json", "SHA256SUMS")
SITE_PREFIXES = ("site/", "manifests/", "claims/", "configs/")
SITE_FILES = ("snapshot/manifest.json", "snapshot/coverage.parquet")
BUNDLES = ("site", "full")
CHUNK_LIMIT = 1_900_000_000


class ReleaseError(Exception):
    pass


def bundle_of(rel: str) -> str:
    if rel in META_FILES:
        return "meta"
    if rel.startswith(SITE_PREFIXES) or rel in SITE_FILES:
        return "site"
    return "full"


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _read_sums(p: Path) -> dict[str, str]:
    listed = {}
    for line in p.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        if rel:
            listed[rel] = digest
    return listed


def _slices_match(p: Path, digests: list[str], limit: int) -> bool:
    """Hash a reassembled file in `limit`-byte slices against its part hashes."""
    got = []
    with p.open("rb") as fh:
        while True:
            h, left, seen = hashlib.sha256(), limit, 0
            while left > 0:
                block = fh.read(min(1 << 20, left))
                if not block:
                    break
                h.update(block)
                left -= len(block)
                seen += len(block)
            if not seen:
                break
            got.append(h.hexdigest())
    return got == digests


def verify_release(
    release_dir: Path, bundles=None, chunk_limit: int | None = None
) -> dict:
    """Check every SHA256SUMS line for the bundles present, and schema_version.

    `bundles=None` checks the site bundle plus the full bundle when any of its files
    is present. A file reassembled from chunks is checked slice by slice.
    """
    release_dir = Path(release_dir)
    result = {
        "ok": False,
        "bad": [],
        "missing": [],
        "extra": [],
        "schema_version": None,
    }
    manifest = _read_json(release_dir / "release_manifest.json")
    sums = release_dir / "SHA256SUMS"
    if manifest is None or not sums.is_file():
        result["missing"] = [m for m in META_FILES if not (release_dir / m).is_file()]
        return result
    result["schema_version"] = manifest.get("schema_version")
    listed = _read_sums(sums)
    chunks = manifest.get("chunks") or {}
    if bundles is None:
        present = [r for r in list(listed) + list(chunks) if (release_dir / r).exists()]
        bundles = (
            ("site", "full")
            if any(bundle_of(r) == "full" for r in present)
            else ("site",)
        )
    wanted = {r: d for r, d in listed.items() if bundle_of(r) in bundles}
    limit = chunk_limit or manifest.get("chunk_limit") or CHUNK_LIMIT
    bad, missing, covered = [], [], set()
    for whole, parts in chunks.items():
        if not any(p in wanted for p in parts):
            continue
        wf = release_dir / whole
        if wf.is_file() and not any((release_dir / p).exists() for p in parts):
            covered.update(parts)
            if not _slices_match(wf, [listed.get(p, "") for p in parts], limit):
                bad.append(whole)
    for rel in sorted(wanted):
        if rel in covered:
            continue
        f = release_dir / rel
        if not f.is_file():
            missing.append(rel)
        elif _sha256_file(f) != wanted[rel]:
            bad.append(rel)
    known = set(listed) | set(META_FILES) | set(chunks)
    extra = sorted(
        r
        for r in (
            f.relative_to(release_dir).as_posix()
            for f in release_dir.rglob("*")
            if f.is_file()
        )
        if r not in known
    )
    result.update(bad=sorted(bad), missing=missing, extra=extra)
    result["ok"] = (
        not bad
        and not missing
        and not extra
        and result["schema_version"] == contracts.SCHEMA_VERSION
    )
    return result


def reassemble(directory: Path, chunks: dict[str, list[str]]) -> list[str]:
    """Join `<name>.partNNN` files back into `<name>` when every part is present."""
    done = []
    for whole, parts in chunks.items():
        part_paths = [directory / p for p in parts]
        if not part_paths or not all(p.is_file() for p in part_paths):
            continue
        target = directory / whole
        tmp = target.with_name(target.name + ".joining")
        with tmp.open("wb") as out:
            for p in part_paths:
                with p.open("rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
        tmp.replace(target)
        for p in part_paths:
            p.unlink()
        done.append(whole)
    return done


def _meta_mode(site_dir: Path) -> str | None:
    import pyarrow.parquet as pq

    try:
        meta = pq.read_table(site_dir / "meta.parquet").to_pydict()
    except (FileNotFoundError, OSError):
        return None
    return dict(zip(meta.get("key", []), meta.get("value", []))).get("mode")


def add_site_tables(release_dir: Path, site_dir: Path) -> list[str]:
    """Copy real, gate-clean site tables into <release>/site and re-hash.

    Refuses (leaving the release untouched) unless every site table is present,
    meta.mode == "real", the text gate passes, and the secret scan is clean.
    """
    from atlas.sitedata.tables import SITE_TABLES

    release_dir, site_dir = Path(release_dir), Path(site_dir)
    names = sorted(SITE_TABLES)
    absent = [n for n in names if not (site_dir / f"{n}.parquet").is_file()]
    if absent:
        raise ReleaseError("site tables missing: " + ", ".join(absent))
    if _meta_mode(site_dir) != "real":
        raise ReleaseError("site tables need meta.mode == real")
    target = release_dir / "site"
    if target.exists():
        raise ReleaseError(f"{target} already exists")
    report = verify_release(release_dir, bundles=BUNDLES)
    if not report["ok"]:
        raise ReleaseError(f"release does not verify: {report}")
    staging = release_dir.parent / f".{release_dir.name}.site.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for n in names:
            shutil.copy2(site_dir / f"{n}.parquet", staging / f"{n}.parquet")
        problems = text_gate(staging) + [str(f) for f in scan_release(staging)]
        if problems:
            raise ReleaseError("site tables blocked:\n" + "\n".join(problems))
        shutil.move(str(staging), str(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    listed = _read_sums(release_dir / "SHA256SUMS")
    added = 0
    for n in names:
        f = target / f"{n}.parquet"
        listed[f"site/{n}.parquet"] = _sha256_file(f)
        added += f.stat().st_size
    (release_dir / "SHA256SUMS").write_text(
        "".join(f"{listed[r]}  {r}\n" for r in sorted(listed))
    )
    manifest_path = release_dir / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["site_tables"] = names
    manifest["file_count"] = manifest.get("file_count", 0) + len(names)
    manifest["total_bytes"] = manifest.get("total_bytes", 0) + added
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return names


def _write_tar_zst(src: Path, members: list[str], dest: Path) -> None:
    import zstandard

    cctx = zstandard.ZstdCompressor(level=10, threads=-1)
    with (
        dest.open("wb") as fh,
        cctx.stream_writer(fh, closefd=False) as zw,
        tarfile.open(fileobj=zw, mode="w|", format=tarfile.PAX_FORMAT) as tf,
    ):
        for rel in members:
            p = src / rel
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = p.stat().st_size, 0, 0o644
            with p.open("rb") as f:
                tf.addfile(info, f)


def pack_release(release_dir: Path, out_dir: Path, limit: int = CHUNK_LIMIT) -> dict:
    """Write site/full bundles (chunked above `limit`) and assets-<tag>.json."""
    release_dir, out_dir = Path(release_dir), Path(out_dir)
    manifest = _read_json(release_dir / "release_manifest.json") or {}
    tag = manifest.get("release")
    if not tag:
        raise ReleaseError("release_manifest.json has no release tag")
    report = verify_release(release_dir, bundles=BUNDLES, chunk_limit=limit)
    if not report["ok"]:
        raise ReleaseError(f"release does not verify: {report}")
    files = sorted(
        f.relative_to(release_dir).as_posix()
        for f in release_dir.rglob("*")
        if f.is_file()
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / f"assets-{tag}.json").exists():
        raise ReleaseError(f"assets for {tag} already exist in {out_dir}")
    tmp = out_dir / f".{tag}.pack"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    index = {
        "release": tag,
        "schema_version": manifest.get("schema_version"),
        "bundles": {},
    }
    try:
        for b in BUNDLES:
            members = [r for r in files if bundle_of(r) in (b, "meta")]
            _write_tar_zst(release_dir, members, tmp / f"{b}-{tag}.tar.zst")
        parts = chunk_large_files(tmp, limit=limit)
        for b in BUNDLES:
            name = f"{b}-{tag}.tar.zst"
            index["bundles"][b] = [
                {
                    "name": n,
                    "sha256": _sha256_file(tmp / n),
                    "bytes": (tmp / n).stat().st_size,
                }
                for n in parts.get(name, [name])
            ]
        for assets in index["bundles"].values():
            for a in assets:
                (tmp / a["name"]).replace(out_dir / a["name"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (out_dir / f"assets-{tag}.json").write_text(json.dumps(index, indent=2) + "\n")
    return index

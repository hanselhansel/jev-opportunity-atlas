"""Restore a public release over plain HTTPS: download each asset listed in
`assets-<tag>.json`, check its sha256, unpack safely, verify, and reassemble.

No gh auth is needed; `gh release download` is an optional alternative. Bundle
layout, verification, and packing live in `atlas.publication.bundles`.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from atlas import contracts
from atlas.publication.bundles import (  # noqa: F401  (re-exported API)
    BUNDLES,
    ReleaseError,
    _read_json,
    add_site_tables,
    bundle_of,
    pack_release,
    reassemble,
    verify_release,
)
from atlas.publication.export import _sha256_file

DEFAULT_REPO = "hanselhansel/jev-opportunity-atlas"
_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class _Chain(io.RawIOBase):
    """Read several files back to back as one stream (chunked assets)."""

    def __init__(self, paths: list[Path]) -> None:
        self._paths, self._fh = list(paths), None

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while True:
            if self._fh is None:
                if not self._paths:
                    return 0
                self._fh = self._paths.pop(0).open("rb")
            n = self._fh.readinto(b)
            if n:
                return n
            self._fh.close()
            self._fh = None


def _safe_member(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if not name or "\\" in name or p.is_absolute() or ".." in p.parts:
        raise ReleaseError(f"unsafe path in bundle: {name!r}")
    return p


def _extract(parts: list[Path], out: Path) -> None:
    import zstandard

    try:
        reader = zstandard.ZstdDecompressor().stream_reader(_Chain(parts))
        with tarfile.open(fileobj=reader, mode="r|") as tf:
            for m in tf:
                rel = _safe_member(m.name)
                if m.isdir():
                    continue
                if not m.isfile():
                    raise ReleaseError(f"unsupported member type in bundle: {m.name!r}")
                dest = out.joinpath(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                with dest.open("wb") as fh:
                    shutil.copyfileobj(src, fh, 1 << 20)
    except (zstandard.ZstdError, tarfile.TarError) as exc:
        raise ReleaseError(f"bundle unreadable: {type(exc).__name__}") from exc


def _http_fetcher(tag: str, repo: str, dl: Path, transport):
    import httpx

    base = f"https://github.com/{repo}/releases/download/{tag}"
    client = httpx.Client(
        transport=transport,
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=30.0),
    )

    def fetch(name: str) -> Path:
        dest = dl / name
        try:
            with client.stream("GET", f"{base}/{name}") as resp:
                if resp.status_code != 200:
                    raise ReleaseError(
                        f"download failed: {name}: HTTP {resp.status_code}"
                    )
                with dest.open("wb") as fh:
                    for block in resp.iter_bytes(1 << 20):
                        fh.write(block)
        except httpx.HTTPError as exc:
            raise ReleaseError(
                f"download failed: {name}: {type(exc).__name__}"
            ) from exc
        return dest

    return fetch, client.close


def _gh_fetcher(tag: str, repo: str, dl: Path):
    if shutil.which("gh") is None:
        raise ReleaseError("gh is not installed; restore without --gh uses plain HTTPS")

    def fetch(name: str) -> Path:
        cmd = ["gh", "release", "download", tag, "-R", repo, "-D", str(dl), "-p", name]
        if subprocess.run(cmd, check=False).returncode != 0:
            raise ReleaseError(f"gh release download failed: {name}")
        return dl / name

    return fetch, lambda: None


def restore(
    tag: str,
    dest: Path,
    bundles=("site",),
    repo: str = DEFAULT_REPO,
    transport=None,
    use_gh: bool = False,
) -> dict:
    """Download, hash-check, unpack, verify, and reassemble into <dest>/<tag>.

    Nothing lands at <dest>/<tag> unless every step passes.
    """
    bundles = tuple(bundles)
    if not bundles or any(b not in BUNDLES for b in bundles):
        raise ReleaseError(f"bundles must be drawn from {BUNDLES}")
    dest = Path(dest)
    final = dest / tag
    if final.exists():
        raise ReleaseError(f"{final} already exists")
    work = dest / f".{tag}.restore"
    shutil.rmtree(work, ignore_errors=True)
    dl, out = work / "download", work / tag
    dl.mkdir(parents=True)
    out.mkdir()
    fetch, close = (
        _gh_fetcher(tag, repo, dl)
        if use_gh
        else _http_fetcher(tag, repo, dl, transport)
    )
    try:
        index = _read_json(fetch(f"assets-{tag}.json"))
        if not index or index.get("release") != tag:
            raise ReleaseError(f"assets-{tag}.json is missing or names another release")
        if index.get("schema_version") != contracts.SCHEMA_VERSION:
            raise ReleaseError(
                f"schema_version {index.get('schema_version')} is not supported"
            )
        for b in bundles:
            assets = (index.get("bundles") or {}).get(b) or []
            if not assets:
                raise ReleaseError(f"bundle {b} is not in assets-{tag}.json")
            parts = []
            for a in assets:
                name = str(a.get("name", ""))
                if not _ASSET_NAME.match(name):
                    raise ReleaseError(f"unsafe asset name: {name!r}")
                p = fetch(name)
                if _sha256_file(p) != a.get("sha256"):
                    raise ReleaseError(f"hash mismatch: {name}")
                parts.append(p)
            _extract(parts, out)
            for p in parts:
                p.unlink()
        report = verify_release(out, bundles=bundles)
        if not report["ok"]:
            raise ReleaseError(
                f"release does not verify: bad={report['bad']} missing={report['missing']} "
                f"extra={report['extra']} schema_version={report['schema_version']}"
            )
        manifest = _read_json(out / "release_manifest.json") or {}
        reassemble(out, manifest.get("chunks") or {})
        out.rename(final)
    finally:
        close()
        shutil.rmtree(work, ignore_errors=True)
    report["bundles"] = list(bundles)
    report["release_dir"] = str(final)
    return report

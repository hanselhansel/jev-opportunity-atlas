import hashlib
import io
import json
import re
import shutil
import tarfile
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts
from atlas.publication.allowlist import text_gate
from atlas.publication.export import (
    _write_sha256sums,
    chunk_large_files,
    stage_release,
)
from atlas.publication.restore import (
    ReleaseError,
    add_site_tables,
    pack_release,
    reassemble,
    restore,
    verify_release,
)
from atlas.sitedata.tables import SITE_TABLES
from tests.publication.test_export import make_workspace


def clean_site_tables(dir: Path) -> Path:
    """Fixture-derived site tables with mode == 'real' and every column the
    text gate flags dropped. Returns the directory of <name>.parquet files."""
    from atlas.sitedata.fixtures import fixture_tables

    tables = fixture_tables(0)
    meta = tables["meta"].to_pydict()
    meta["value"] = [
        "real" if k == "mode" else v for k, v in zip(meta["key"], meta["value"])
    ]
    tables["meta"] = pa.Table.from_pydict(meta, schema=SITE_TABLES["meta"])
    out = Path(dir)
    out.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        for name, table in tables.items():
            pq.write_table(table, out / f"{name}.parquet", compression="zstd")
        problems = text_gate(out)
        if not problems:
            return out
        for problem in problems:
            m = re.match(
                r"text-gate (?:forbidden-field|long-strings) ([^:]+):(\w+)",
                problem,
            )
            assert m, problem
            stem, col = Path(m.group(1)).stem, m.group(2)
            tables[stem] = tables[stem].drop_columns(col)
    raise AssertionError("site tables never became gate-clean")


def gh_transport(out_dir: Path, tag: str, mutate=None):
    def handler(request):
        assert request.url.host == "github.com"
        prefix = f"/hanselhansel/jev-opportunity-atlas/releases/download/{tag}/"
        assert request.url.path.startswith(prefix), request.url.path
        name = request.url.path[len(prefix):]
        data = (out_dir / name).read_bytes()
        if mutate and name != f"assets-{tag}.json":
            data = mutate(data)
        return httpx.Response(200, content=data)

    return httpx.MockTransport(handler)


def test_verify_passes_then_detects_tamper(tmp_path):
    ws = make_workspace(tmp_path)
    out = stage_release(ws, "v0-test", "s1", ["r1"])
    assert verify_release(out)["ok"] is True
    (out / "runs" / "r1" / "ledger.jsonl").write_text("changed\n")
    report = verify_release(out)
    assert report["ok"] is False
    assert report["bad"] == ["runs/r1/ledger.jsonl"]


def test_chunks_reassemble(tmp_path):
    d = tmp_path / "rel"
    d.mkdir()
    (d / "big.bin").write_bytes(b"x" * 2500)
    chunks = chunk_large_files(d, limit=1000)
    assert len(chunks["big.bin"]) == 3
    assert not (d / "big.bin").exists()
    reassemble(d, chunks)
    assert (d / "big.bin").read_bytes() == b"x" * 2500


def test_pack_download_restore_round_trip(tmp_path):
    ws = make_workspace(tmp_path / "ws")
    (ws / "claims").mkdir()
    (ws / "claims" / "claims.yaml").write_text("[]\n")
    rel = stage_release(ws, "v1-test", "s1", ["r1"])
    site_data = clean_site_tables(tmp_path / "sitedata")
    names = add_site_tables(rel, site_data)
    assert names == sorted(SITE_TABLES)
    manifest = json.loads((rel / "release_manifest.json").read_text())
    assert manifest["site_tables"] == sorted(SITE_TABLES)
    out_dir = tmp_path / "assets"
    index = pack_release(rel, out_dir)
    assert index["release"] == "v1-test"
    assert [a["name"] for a in index["bundles"]["site"]] == [
        "site-v1-test.tar.zst"
    ]
    transport = gh_transport(out_dir, "v1-test")
    report = restore("v1-test", tmp_path / "r1", transport=transport)
    assert report["ok"] is True
    assert report["bundles"] == ["site"]
    restored = tmp_path / "r1" / "v1-test"
    assert (restored / "site" / "meta.parquet").exists()
    assert (restored / "claims" / "claims.yaml").exists()
    assert (restored / "snapshot" / "manifest.json").exists()
    assert not (restored / "snapshot" / "comments_public.parquet").exists()
    assert not (restored / "runs").exists()
    report = restore(
        "v1-test",
        tmp_path / "r2",
        bundles=("site", "full"),
        transport=transport,
    )
    assert report["ok"] is True
    assert report["bundles"] == ["site", "full"]
    assert (tmp_path / "r2" / "v1-test" / "runs" / "r1" / "ledger.jsonl").exists()


def test_tampered_asset_rejected(tmp_path):
    ws = make_workspace(tmp_path / "ws")
    rel = stage_release(ws, "v2-test", "s1", ["r1"])
    add_site_tables(rel, clean_site_tables(tmp_path / "sitedata"))
    out_dir = tmp_path / "assets"
    pack_release(rel, out_dir)

    def flip(data: bytes) -> bytes:
        return data[:10] + bytes([data[10] ^ 0xFF]) + data[11:]

    transport = gh_transport(out_dir, "v2-test", mutate=flip)
    with pytest.raises(ReleaseError) as exc:
        restore("v2-test", tmp_path / "r", transport=transport)
    assert "site-v2-test.tar.zst" in str(exc.value)
    assert not (tmp_path / "r" / "v2-test").exists()


def test_chunked_asset_download(tmp_path):
    ws = make_workspace(tmp_path / "ws")
    rel = stage_release(ws, "v3-test", "s1", ["r1"])
    add_site_tables(rel, clean_site_tables(tmp_path / "sitedata"))
    out_dir = tmp_path / "assets"
    index = pack_release(rel, out_dir, limit=5000)
    site_assets = index["bundles"]["site"]
    assert len(site_assets) > 1
    assert site_assets[0]["name"].endswith(".part000")
    transport = gh_transport(out_dir, "v3-test")
    report = restore("v3-test", tmp_path / "r", transport=transport)
    assert report["ok"] is True
    assert (tmp_path / "r" / "v3-test" / "site" / "meta.parquet").exists()


def _manual_chunked_release(d: Path, size: int = 2500, limit: int = 1000) -> dict:
    (d / "runs" / "r1").mkdir(parents=True)
    (d / "runs" / "r1" / "big.bin").write_bytes(bytes(range(256)) * (size // 256))
    chunks = chunk_large_files(d, limit=limit)
    _write_sha256sums(d)
    manifest = {
        "release": "v9-chunked",
        "schema_version": contracts.SCHEMA_VERSION,
        "chunks": chunks,
    }
    (d / "release_manifest.json").write_text(json.dumps(manifest))
    return chunks


def test_in_release_chunked_file(tmp_path):
    rel = tmp_path / "rel"
    chunks = _manual_chunked_release(rel)
    assert chunks == {
        "runs/r1/big.bin": [
            "runs/r1/big.bin.part000",
            "runs/r1/big.bin.part001",
            "runs/r1/big.bin.part002",
        ]
    }
    assert verify_release(rel)["ok"] is True
    reassemble(rel, chunks)
    report = verify_release(rel, chunk_limit=1000)
    assert report["ok"] is True
    data = (rel / "runs" / "r1" / "big.bin").read_bytes()
    (rel / "runs" / "r1" / "big.bin").write_bytes(data[:7] + b"!" + data[8:])
    report = verify_release(rel, chunk_limit=1000)
    assert report["ok"] is False
    assert report["bad"] == ["runs/r1/big.bin"]


def test_restore_reassembles_in_release_chunks(tmp_path):
    rel = tmp_path / "rel"
    _manual_chunked_release(rel)
    out_dir = tmp_path / "assets"
    pack_release(rel, out_dir)
    transport = gh_transport(out_dir, "v9-chunked")
    report = restore(
        "v9-chunked",
        tmp_path / "r",
        bundles=("full",),
        transport=transport,
    )
    assert report["ok"] is True
    restored = tmp_path / "r" / "v9-chunked"
    assert (restored / "runs" / "r1" / "big.bin").read_bytes() == (
        bytes(range(256)) * 9
    )
    assert not list(restored.rglob("*.part*"))


def test_unsafe_tar_member_rejected(tmp_path):
    import zstandard

    tag = "v4-evil"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        payload = b"evil"
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    out_dir = tmp_path / "assets"
    out_dir.mkdir()
    blob = zstandard.ZstdCompressor().compress(buf.getvalue())
    asset = out_dir / f"site-{tag}.tar.zst"
    asset.write_bytes(blob)
    index = {
        "release": tag,
        "schema_version": contracts.SCHEMA_VERSION,
        "bundles": {
            "site": [
                {
                    "name": asset.name,
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "bytes": len(blob),
                }
            ],
            "full": [],
        },
    }
    (out_dir / f"assets-{tag}.json").write_text(json.dumps(index))
    transport = gh_transport(out_dir, tag)
    with pytest.raises(ReleaseError):
        restore(tag, tmp_path / "r", transport=transport)


def test_add_site_tables_refusals(tmp_path):
    ws = make_workspace(tmp_path / "ws")
    rel = stage_release(ws, "v5-test", "s1", ["r1"])
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    from atlas.sitedata.fixtures import fixture_tables

    for name, table in fixture_tables(0).items():
        pq.write_table(table, fixture_dir / f"{name}.parquet")
    with pytest.raises(ReleaseError):
        add_site_tables(rel, fixture_dir)
    assert not (rel / "site").exists()

    dirty = tmp_path / "dirty"
    shutil.copytree(clean_site_tables(tmp_path / "clean"), dirty)
    bad = pq.read_table(dirty / "quality.parquet")
    bad = bad.append_column("author", pa.array(["u"] * bad.num_rows))
    pq.write_table(bad, dirty / "quality.parquet")
    before = sorted(p.relative_to(rel).as_posix() for p in rel.rglob("*"))
    with pytest.raises(ReleaseError):
        add_site_tables(rel, dirty)
    after = sorted(p.relative_to(rel).as_posix() for p in rel.rglob("*"))
    assert before == after


def test_schema_mismatch_in_index_rejected(tmp_path):
    ws = make_workspace(tmp_path / "ws")
    rel = stage_release(ws, "v6-test", "s1", ["r1"])
    add_site_tables(rel, clean_site_tables(tmp_path / "sitedata"))
    out_dir = tmp_path / "assets"
    pack_release(rel, out_dir)
    index_path = out_dir / "assets-v6-test.json"
    index = json.loads(index_path.read_text())
    index["schema_version"] = contracts.SCHEMA_VERSION + 1
    index_path.write_text(json.dumps(index))
    with pytest.raises(ReleaseError):
        restore("v6-test", tmp_path / "r", transport=gh_transport(out_dir, "v6-test"))
    assert not (tmp_path / "r" / "v6-test").exists()


def test_restore_with_gh_uses_release_download(tmp_path, monkeypatch):
    from atlas.publication import restore as restore_mod

    ws = make_workspace(tmp_path / "ws")
    rel = stage_release(ws, "v7-test", "s1", ["r1"])
    add_site_tables(rel, clean_site_tables(tmp_path / "sitedata"))
    out_dir = tmp_path / "assets"
    pack_release(rel, out_dir)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd[:4] == ["gh", "release", "download", "v7-test"]
        dest = Path(cmd[cmd.index("-D") + 1])
        name = cmd[cmd.index("-p") + 1]
        shutil.copy2(out_dir / name, dest / name)

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(restore_mod.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(restore_mod.subprocess, "run", fake_run)
    report = restore("v7-test", tmp_path / "r", use_gh=True)
    assert report["ok"] is True
    assert all("-R" in c and "hanselhansel/jev-opportunity-atlas" in c for c in calls)


def test_restore_refuses_existing_destination(tmp_path):
    (tmp_path / "r" / "v8-test").mkdir(parents=True)
    with pytest.raises(ReleaseError):
        restore("v8-test", tmp_path / "r", transport=httpx.MockTransport(lambda r: None))


def test_cli_pack_then_restore(tmp_path, monkeypatch, capsys):
    import argparse

    from atlas import paths
    from atlas.publication import cli as pubcli
    from atlas.publication import restore as restore_mod

    ws = make_workspace(tmp_path / "ws")
    stage_release(ws, "v10-test", "s1", ["r1"])
    monkeypatch.setattr(paths, "EXPORTS", ws / "exports")
    monkeypatch.setattr(paths, "DATA", ws / "data")
    site_data = clean_site_tables(tmp_path / "sitedata")
    pubcli._release_pack(
        argparse.Namespace(
            release="v10-test", site_data=str(site_data), out=None, chunk_limit=10**9
        )
    )
    assets = ws / "exports" / "v10-test-assets"
    assert (assets / "assets-v10-test.json").exists()
    capsys.readouterr()
    real_restore = restore_mod.restore

    def fake_restore(tag, dest, **kwargs):
        kwargs.pop("use_gh")
        return real_restore(tag, dest, transport=gh_transport(assets, tag), **kwargs)

    monkeypatch.setattr(restore_mod, "restore", fake_restore)
    pubcli._release_restore(
        argparse.Namespace(
            release="v10-test", dest=None, bundle=None, repo=restore_mod.DEFAULT_REPO,
            gh=False,
        )
    )
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert (ws / "data" / "releases" / "v10-test" / "site" / "meta.parquet").exists()

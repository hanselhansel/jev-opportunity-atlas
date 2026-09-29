import asyncio
import hashlib
import json

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.publication.rehydrate import rehydrate, rehydrate_release


def h(t):
    return hashlib.sha256(t.encode()).hexdigest()


def item_handler(items):
    async def handler(request):
        assert request.url.host == "hn.test"
        i = int(request.url.path.rsplit("/", 1)[1].split(".")[0])
        if items.get(i) == "boom":
            return httpx.Response(404)
        return httpx.Response(200, content=json.dumps(items.get(i)).encode())

    return handler


def test_matches_changed_and_missing():
    items = {
        1: {"id": 1, "text": "Same text"},
        2: {"id": 2, "text": "Edited later"},
        3: None,
    }
    expected = {1: h("Same text"), 2: h("Original"), 3: h("Gone")}
    out = asyncio.run(
        rehydrate(
            expected,
            transport=httpx.MockTransport(item_handler(items)),
            concurrency=2,
            api_base="https://hn.test/v0",
            normalize=lambda t: t,
        )
    )
    assert out["texts"][1] == "Same text"
    assert out["status"] == {1: "match", 2: "changed", 3: "missing"}
    assert out["summary"] == {"match": 1, "changed": 1, "missing": 1}


def test_default_normalize_is_html_to_text_and_dead_is_missing():
    items = {
        9_000_000_001: {"id": 9_000_000_001, "text": "a &amp; b<p>second"},
        9_000_000_002: {"id": 9_000_000_002, "deleted": True},
        9_000_000_003: {"id": 9_000_000_003, "dead": True, "text": "x"},
        9_000_000_004: "boom",
    }
    expected = {
        9_000_000_001: h("a & b\n\nsecond"),
        9_000_000_002: h("x"),
        9_000_000_003: h("x"),
        9_000_000_004: h("x"),
    }
    out = asyncio.run(
        rehydrate(
            expected,
            transport=httpx.MockTransport(item_handler(items)),
            api_base="https://hn.test/v0",
        )
    )
    assert out["status"] == {
        9_000_000_001: "match",
        9_000_000_002: "missing",
        9_000_000_003: "missing",
        9_000_000_004: "failed",
    }
    assert set(out["texts"]) == {9_000_000_001}


def _release(tmp_path, with_snapshot=True):
    rel = tmp_path / "exports" / "v0-test"
    if with_snapshot:
        (rel / "snapshot").mkdir(parents=True)
        pq.write_table(
            pa.table(
                {
                    "id": [9_000_000_002, 9_000_000_001],
                    "text_sha256": [h("two"), h("one")],
                }
            ),
            rel / "snapshot" / "comments_public.parquet",
        )
    else:
        (rel / "site").mkdir(parents=True)
        pq.write_table(
            pa.table({"comment_id": [9_000_000_001], "text_sha256": [h("one")]}),
            rel / "site" / "evidence.parquet",
        )
    return rel


def test_rehydrate_release_writes_only_under_out_root(tmp_path):
    rel = _release(tmp_path)
    before = sorted(p.as_posix() for p in rel.rglob("*"))
    items = {
        9_000_000_001: {"id": 9_000_000_001, "text": "one"},
        9_000_000_002: {"id": 9_000_000_002, "text": "two, edited"},
    }
    out_root = tmp_path / "data" / "rehydrated"
    summary = rehydrate_release(
        rel,
        out_root,
        transport=httpx.MockTransport(item_handler(items)),
        api_base="https://hn.test/v0",
    )
    assert summary["summary"] == {"match": 1, "changed": 1}
    assert summary["no_longer_matching_share"] == 0.5
    assert sorted(p.as_posix() for p in rel.rglob("*")) == before
    table = pq.read_table(out_root / "v0-test" / "texts.parquet").to_pydict()
    assert table["id"] == [9_000_000_001, 9_000_000_002]
    assert table["status"] == ["match", "changed"]
    saved = json.loads((out_root / "v0-test" / "summary.json").read_text())
    assert saved["summary"] == {"match": 1, "changed": 1}


def test_rehydrate_release_falls_back_to_site_evidence_and_limit(tmp_path):
    rel = _release(tmp_path, with_snapshot=False)
    items = {9_000_000_001: {"id": 9_000_000_001, "text": "one"}}
    summary = rehydrate_release(
        rel,
        tmp_path / "out",
        limit=1,
        transport=httpx.MockTransport(item_handler(items)),
        api_base="https://hn.test/v0",
    )
    assert summary["summary"] == {"match": 1}
    assert summary["source"] == "site/evidence.parquet"


def test_rehydrate_release_refuses_out_root_inside_release(tmp_path):
    rel = _release(tmp_path)
    with pytest.raises(ValueError):
        rehydrate_release(
            rel, rel / "rehydrated", transport=httpx.MockTransport(lambda r: None)
        )


def test_cli_writes_to_data_rehydrated(tmp_path, monkeypatch, capsys):
    import argparse

    from atlas import paths
    from atlas.publication import cli as pubcli
    from atlas.publication import rehydrate as rehydrate_mod

    rel = _release(tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    items = {
        9_000_000_001: {"id": 9_000_000_001, "text": "one"},
        9_000_000_002: {"id": 9_000_000_002, "text": "two"},
    }
    real = rehydrate_mod.rehydrate_release

    def with_mock(release_dir, out_root, **kwargs):
        assert out_root == tmp_path / "data" / "rehydrated"
        return real(
            release_dir,
            out_root,
            transport=httpx.MockTransport(item_handler(items)),
            api_base="https://hn.test/v0",
            **kwargs,
        )

    monkeypatch.setattr(rehydrate_mod, "rehydrate_release", with_mock)
    pubcli._release_rehydrate(
        argparse.Namespace(release_dir=str(rel), limit=None, concurrency=4)
    )
    out = json.loads(capsys.readouterr().out)
    assert out["summary"] == {"match": 2}
    assert (tmp_path / "data" / "rehydrated" / "v0-test" / "texts.parquet").exists()

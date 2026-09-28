"""Discovery lane: match hit IDs to the snapshot frame; `discover search` CLI."""

import json

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.discovery.match import match_hits

BASE = 9_000_000_000


def write_comments(snapshot_dir, rows):
    """Write a comments.parquet; row dicts only need the fields they set."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=contracts.COMMENTS)
    pq.write_table(table, snapshot_dir / "comments.parquet")


def test_match_hits_frame(tmp_path):
    write_comments(
        tmp_path,
        [
            {"id": BASE + 1, "eligible": True, "in_window": True, "state": "ok"},
            {"id": BASE + 2, "eligible": True, "in_window": True, "state": "ok"},
        ],
    )
    out = match_hits([BASE + 1, BASE + 2, BASE + 99], tmp_path)
    assert out == {
        "in_frame": [BASE + 1, BASE + 2],
        "outside_frame": [BASE + 99],
        "ineligible": [],
    }


def test_match_hits_ineligible_and_duplicates(tmp_path):
    write_comments(
        tmp_path,
        [
            {"id": BASE + 1, "eligible": True, "in_window": True, "state": "ok"},
            {
                "id": BASE + 3,
                "eligible": False,
                "in_window": False,
                "state": "ok",
                "exclusion_reason": "out_of_window",
            },
        ],
    )
    out = match_hits([BASE + 1, BASE + 3, BASE + 3, BASE + 5], tmp_path)
    assert out == {
        "in_frame": [BASE + 1],
        "outside_frame": [BASE + 5],
        "ineligible": [BASE + 3],
    }


def test_match_hits_empty(tmp_path):
    assert match_hits([], tmp_path) == {
        "in_frame": [],
        "outside_frame": [],
        "ineligible": [],
    }


def test_match_hits_missing_parquet(tmp_path):
    with pytest.raises(FileNotFoundError):
        match_hits([BASE + 1], tmp_path)


def test_run_search_end_to_end(tmp_path, monkeypatch):
    from atlas.discovery.cli import run_search

    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "DISCOVERY", tmp_path / "discovery")
    write_comments(
        tmp_path / "snapshots" / "snap1",
        [
            {"id": BASE + 1, "eligible": True, "in_window": True, "state": "ok"},
            {
                "id": BASE + 2,
                "eligible": False,
                "in_window": False,
                "state": "ok",
                "exclusion_reason": "out_of_window",
            },
        ],
    )
    hits_by_query = {
        "qa": [
            {"objectID": str(BASE + 1), "created_at_i": 100, "story_id": BASE + 50}
        ],
        "qb": [
            {"objectID": str(BASE + 2), "created_at_i": 200, "story_id": BASE + 50},
            {"objectID": str(BASE + 3), "created_at_i": 300, "story_id": None},
        ],
    }

    def handler(request):
        hits = hits_by_query[request.url.params["query"]]
        return httpx.Response(
            200, json={"nbHits": len(hits), "hits": hits, "nbPages": 1}
        )

    manifest = run_search(
        "case-one",
        ["qa", "qb"],
        snapshot_id="snap1",
        transport=httpx.MockTransport(handler),
        pause_s=0,
    )
    out_dir = tmp_path / "discovery" / "case-one"
    for name in ("hits.parquet", "requests.jsonl", "manifest.json"):
        assert (out_dir / name).exists()

    table = pq.read_table(out_dir / "hits.parquet")
    assert table.column_names == [
        "id",
        "created_at_i",
        "story_id",
        "query",
        "lane",
        "frame",
    ]
    rows = {r["id"]: r for r in table.to_pylist()}
    assert all(r["lane"] == "discovery" for r in rows.values())
    assert rows[BASE + 1]["frame"] == "in_frame"
    assert rows[BASE + 2]["frame"] == "ineligible"
    assert rows[BASE + 3]["frame"] == "outside_frame"
    assert rows[BASE + 3]["story_id"] is None

    counts = manifest["counts"]
    assert counts["requests"] == 2
    assert counts["hit_rows"] == 3 and counts["unique_ids"] == 3
    assert counts["in_frame"] == 1
    assert counts["ineligible"] == 1
    assert counts["outside_frame"] == 1
    assert counts["per_query"] == {"qa": 1, "qb": 2}
    logged = [
        json.loads(line)
        for line in (out_dir / "requests.jsonl").read_text().splitlines()
    ]
    assert [r["query"] for r in logged] == ["qa", "qb"]
    on_disk = json.loads((out_dir / "manifest.json").read_text())
    assert on_disk["snapshot_id"] == "snap1"
    assert on_disk["lane"] == "discovery"


def test_run_search_missing_snapshot(tmp_path, monkeypatch):
    from atlas.discovery.cli import run_search

    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "DISCOVERY", tmp_path / "discovery")
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200, json={"nbHits": 0, "hits": [], "nbPages": 1})

    with pytest.raises(SystemExit):
        run_search(
            "nope",
            ["q"],
            snapshot_id="absent",
            transport=httpx.MockTransport(handler),
            pause_s=0,
        )
    assert called == []


def test_parser_discover_search():
    import atlas.cli

    args = atlas.cli.build_parser().parse_args(
        ["discover", "search", "--name", "x", "--query", "q"]
    )
    assert args.name == "x" and args.query == ["q"] and callable(args.func)

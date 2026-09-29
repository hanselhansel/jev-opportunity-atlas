"""L17 17.4: per-comment screen table — joins, dedup, missing, orphans."""

import json
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.pilot import packed
from atlas.screen import run, unpack
from tests.pilot.test_support import SNAPSHOT_ID, pilot_repo  # noqa: F401
from tests.screen import support

RUN_ID = "screen-r1"


def _dispatched(pilot_repo, monkeypatch, capsys):  # noqa: F811
    sid, ids = support.write_sample()
    support.mock_runtime(monkeypatch, seen=[])
    run.screen_sample(sid, RUN_ID, k=5, chunk=200, yes=True)
    capsys.readouterr()
    return sid, ids


def test_build_screen_table(pilot_repo, monkeypatch, capsys):  # noqa: F811
    sid, ids = _dispatched(pilot_repo, monkeypatch, capsys)
    run_dir = paths.run_dir(RUN_ID)
    table = unpack.build_screen_table(RUN_ID)
    assert table.schema == unpack.SCREEN_BY_COMMENT
    assert table.num_rows == 1000
    rows = table.to_pylist()
    assert [r["comment_id"] for r in rows] == ids  # sorted by comment_id

    sample = {
        r["comment_id"]: r
        for r in pq.read_table(paths.sample_path(sid)).to_pylist()
    }
    comments = pq.read_table(
        paths.snapshot_dir(SNAPSHOT_ID) / "comments.parquet",
        columns=["id", "text_norm"],
    )
    text = {r["id"]: r["text_norm"] for r in comments.to_pylist()}
    slot_of = {
        r["comment_id"]: (r["packed_id"], r["slot"])
        for r in pq.read_table(run_dir / "packed_map.parquet").to_pylist()
    }
    for r in rows:
        s = sample[r["comment_id"]]
        assert r["story_id"] == s["story_id"]
        assert r["stratum"] == s["stratum"]
        assert r["weight"] == pytest.approx(s["weight"])
        assert r["half"] == contracts.half_of(s["story_id"])
        assert r["model_returned"] == "jev-1.13.0"
        assert r["request_id"]
        assert (r["packed_id"], r["slot"]) == slot_of[r["comment_id"]]
        expected = 0.9 if "PAIN" in text[r["comment_id"]] else 0.1
        assert r["firsthand_p"] == expected
    assert (run_dir / "screen_by_comment.parquet").exists()


def test_orphan_part_is_ignored(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _dispatched(pilot_repo, monkeypatch, capsys)
    run_dir = paths.run_dir(RUN_ID)
    # A part written but never recorded in done.jsonl must not count twice.
    shutil.copy(
        run_dir / "answers" / "part-1.parquet",
        run_dir / "answers" / "part-99.parquet",
    )
    table = unpack.build_screen_table(RUN_ID)
    assert table.num_rows == 1000
    assert len(set(table.column("comment_id").to_pylist())) == 1000


def test_missing_answers_raise(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _dispatched(pilot_repo, monkeypatch, capsys)
    run_dir = paths.run_dir(RUN_ID)
    done_path = run_dir / "done.jsonl"
    lines = done_path.read_text().splitlines()
    victim = json.loads(lines[0])["comment_id"]
    kept = [l for l in lines if json.loads(l)["comment_id"] != victim]
    done_path.write_text("\n".join(kept) + "\n")
    with pytest.raises(ValueError, match="missing answers"):
        unpack.build_screen_table(RUN_ID)


def test_duplicate_mapping_raises(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _dispatched(pilot_repo, monkeypatch, capsys)
    run_dir = paths.run_dir(RUN_ID)
    map_dir = run_dir / "packed_map.parquet"
    pmap = pq.read_table(map_dir).to_pylist()
    dup = pmap[0]["comment_id"]
    other_packed = pmap[5]["packed_id"]
    extra = pa.Table.from_pylist(
        [{"packed_id": other_packed, "slot": "c1", "comment_id": dup}],
        schema=packed.PACKED_MAP,
    )
    pq.write_table(extra, map_dir / "part-99999.parquet")
    with pytest.raises(ValueError, match="duplicate"):
        unpack.build_screen_table(RUN_ID)

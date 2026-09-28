"""Discovery lane: match hit IDs to the snapshot frame."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts
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

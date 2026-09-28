"""Match discovery hit IDs to the snapshot's comments.parquet.

Every hit lands in exactly one bucket: in_frame (present and eligible),
ineligible (present but excluded), or outside_frame (absent from the snapshot;
never added to it).
"""

from __future__ import annotations

from pathlib import Path


def match_hits(hit_ids, snapshot_dir) -> dict:
    """Bucket unique hit IDs by snapshot membership and eligibility."""
    ids = sorted({int(i) for i in hit_ids})
    result: dict[str, list[int]] = {
        "in_frame": [],
        "outside_frame": [],
        "ineligible": [],
    }
    if not ids:
        return result
    parquet = Path(snapshot_dir) / "comments.parquet"
    if not parquet.exists():
        raise FileNotFoundError(parquet)

    import duckdb
    import pyarrow as pa

    hits = pa.table({"id": pa.array(ids, type=pa.int64())})
    con = duckdb.connect()
    try:
        con.register("hits", hits)
        rows = con.execute(
            "select h.id, c.id, c.eligible from hits h "
            "left join read_parquet(?) c on c.id = h.id order by h.id",
            [str(parquet)],
        ).fetchall()
    finally:
        con.close()

    for hit_id, comment_id, eligible in rows:
        if comment_id is None:
            result["outside_frame"].append(hit_id)
        elif eligible:
            result["in_frame"].append(hit_id)
        else:
            result["ineligible"].append(hit_id)
    return result

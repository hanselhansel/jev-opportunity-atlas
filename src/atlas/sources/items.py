"""Shared loader: comment text plus parent/story context for downstream lanes.

One DuckDB query over the snapshot's comments/stories/context parquet files,
restricted to the requested ids and their parents. `parent` resolves to the
parent comment's text when present in the scan, else the root story's text,
else the context table's text (ancestors fetched outside the scan range).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa


def _q(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def load_items(snapshot_dir: Path, comment_ids: list[int]) -> list[dict]:
    """Dicts in input order: comment_id, comment, parent, story_title,
    thread_type, sentences, text_sha256. Unknown comment id raises KeyError."""
    import duckdb

    snapshot_dir = Path(snapshot_dir)
    con = duckdb.connect()
    try:
        con.register(
            "wanted",
            pa.table(
                {"id": pa.array([int(i) for i in comment_ids], type=pa.int64())}
            ),
        )
        comments = _q(snapshot_dir / "comments.parquet")
        stories = _q(snapshot_dir / "stories.parquet")
        ctx_file = snapshot_dir / "context.parquet"
        ctx_join = (
            f"LEFT JOIN read_parquet({_q(ctx_file)}) cx ON cx.id = c.parent_id"
            if ctx_file.exists()
            else "LEFT JOIN (SELECT NULL::BIGINT id, NULL::VARCHAR text_norm "
            "WHERE false) cx ON cx.id = c.parent_id"
        )
        rows = con.execute(
            f"""
            SELECT c.id AS comment_id, c.text_norm AS comment,
                   COALESCE(pc.text_norm, ps.text_norm, cx.text_norm, '') AS parent,
                   COALESCE(s.title, '') AS story_title,
                   c.thread_type, c.sentences, c.text_sha256
            FROM read_parquet({comments}) c
            JOIN wanted w ON w.id = c.id
            LEFT JOIN read_parquet({comments}) pc ON pc.id = c.parent_id
            LEFT JOIN read_parquet({stories}) ps ON ps.id = c.parent_id
            {ctx_join}
            LEFT JOIN read_parquet({stories}) s ON s.id = c.story_id
            """
        ).to_arrow_table().to_pylist()
    finally:
        con.close()
    by_id = {r["comment_id"]: r for r in rows}
    out = []
    for i in comment_ids:
        key = int(i)
        if key not in by_id:
            raise KeyError(key)
        out.append(by_id[key])
    return out

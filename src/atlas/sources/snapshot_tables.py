"""Snapshot build pass 3: DuckDB joins and deterministic Parquet output.

Reads the per-shard parts, roots, and context part; joins comment rows with
their resolved root's thread type; applies the eligibility precedence; and
writes comments/stories/context/coverage parquet with fixed 100k-row groups so
the bytes are deterministic. created_at stays an epoch-second int64 through
DuckDB and is cast to timestamp('s','UTC') in pyarrow (no TIMESTAMPTZ, which
would need pytz on the Python side).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts
from atlas.sources.threads import thread_type_of

ROW_GROUP = 100_000


def _rel(paths: list[Path]) -> str:
    lst = ", ".join("'" + str(p).replace("'", "''") + "'" for p in paths)
    return f"read_parquet([{lst}], union_by_name=true)"


def _file(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _align(t: pa.Table, schema: pa.Schema) -> pa.Table:
    cols = []
    for f in schema:
        col = t.column(f.name)
        cols.append(col if col.type.equals(f.type) else col.cast(f.type))
    return pa.Table.from_arrays(cols, schema=schema)


def _write_parquet(reader, schema: pa.Schema, path: Path) -> int:
    """Stream record batches into row groups of exactly ROW_GROUP rows."""
    n = 0
    pending = pa.Table.from_batches([], schema=schema)
    with pq.ParquetWriter(
        str(path), schema, compression="zstd", use_dictionary=True,
        write_statistics=True,
    ) as w:
        for batch in reader:
            t = _align(pa.Table.from_batches([batch]), schema)
            pending = pa.concat_tables([pending, t]) if pending.num_rows else t
            while pending.num_rows >= ROW_GROUP:
                w.write_table(pending.slice(0, ROW_GROUP))
                pending = pending.slice(ROW_GROUP)
                n += ROW_GROUP
        if pending.num_rows:
            w.write_table(pending)
            n += pending.num_rows
    return n


def write_tables(
    con,
    part_paths: list[Path],
    ctx_path: Path | None,
    roots_path: Path,
    out_dir: Path,
    ws: int,
    we: int,
    missing_count: int,
    meta: dict,
) -> dict:
    """Write the four contract tables; return counts for manifest/coverage."""
    parts = _rel(part_paths)
    con.execute(f"CREATE TEMPORARY TABLE scan_parts AS SELECT * FROM {parts}")
    if ctx_path is not None:
        con.execute(
            "CREATE TEMPORARY TABLE ctx AS "
            f"SELECT * FROM {_file(ctx_path)} "
            "WHERE id NOT IN (SELECT id FROM scan_parts)"
        )
    else:
        con.execute(
            "CREATE TEMPORARY TABLE ctx AS "
            "SELECT * FROM scan_parts WHERE false"
        )
    con.execute(
        "CREATE TEMPORARY TABLE all_items AS "
        "SELECT * FROM scan_parts UNION ALL SELECT * FROM ctx"
    )

    root_rows = con.execute(
        "SELECT id, type, title FROM all_items "
        "WHERE type IN ('story','poll','job')"
    ).fetchall()
    tt = {r[0]: thread_type_of(r[1], r[2]) for r in root_rows}
    con.register(
        "tt",
        pa.table(
            {
                "story_id": pa.array(list(tt), type=pa.int64()),
                "thread_type": pa.array(list(tt.values()), type=pa.string()),
            }
        ),
    )

    con.execute(
        f"""
        CREATE TEMPORARY TABLE comments_final AS
        SELECT c.id, c.time, c.time AS created_at,
               strftime(make_timestamp(c.time * 1000000), '%Y-%m') AS month,
               CASE WHEN c.time >= {ws} AND c.time < {we} THEN printf(
                   'P%02d',
                   CAST(FLOOR((c.time - {ws}) * 12 / ({we} - {ws})) AS BIGINT) + 1)
               ELSE NULL END AS period,
               c.parent AS parent_id, r.story_id,
               CAST(r.depth AS SMALLINT) AS depth,
               c.text_norm, c.sentences, c.text_sha256, c.author,
               COALESCE(tt.thread_type, 'unknown') AS thread_type,
               c.state,
               COALESCE(c.time >= {ws} AND c.time < {we}, FALSE) AS in_window,
               c.lang, c.word_count,
               CASE
                   WHEN c.type <> 'comment' THEN 'not_comment'
                   WHEN NOT COALESCE(c.time >= {ws} AND c.time < {we}, FALSE)
                       THEN 'out_of_window'
                   WHEN c.state = 'deleted' THEN 'deleted'
                   WHEN c.state = 'dead' THEN 'dead'
                   WHEN c.text_norm = '' THEN 'empty_text'
                   WHEN c.lang NOT IN ('en','und') THEN 'non_english'
               END AS exclusion_reason
        FROM scan_parts c
        JOIN read_parquet({_file(roots_path)}) r ON r.id = c.id
        LEFT JOIN tt ON tt.story_id = r.story_id
        WHERE c.type = 'comment'
        """
    )
    n_comments = _write_parquet(
        con.execute(
            "SELECT id, time, created_at, month, period, parent_id, story_id,"
            " depth, text_norm, sentences, text_sha256, author, thread_type,"
            " state, in_window, lang, word_count,"
            " (exclusion_reason IS NULL) AS eligible, exclusion_reason"
            " FROM comments_final ORDER BY id"
        ).to_arrow_reader(),
        contracts.COMMENTS,
        out_dir / "comments.parquet",
    )

    n_stories = _write_parquet(
        con.execute(
            "SELECT s.id, s.time, s.time AS created_at, s.type, s.title, s.url,"
            " s.text_norm, CAST(s.score AS INTEGER) score,"
            " CAST(s.descendants AS INTEGER) descendants,"
            " COALESCE(tt.thread_type, 'unknown') thread_type, s.state,"
            f" COALESCE(s.time >= {ws} AND s.time < {we}, FALSE) in_window,"
            " s.fetched_at"
            " FROM all_items s LEFT JOIN tt ON tt.story_id = s.id"
            " WHERE s.type IN ('story','poll','job') ORDER BY s.id"
        ).to_arrow_reader(),
        contracts.STORIES,
        out_dir / "stories.parquet",
    )

    n_context = _write_parquet(
        con.execute(
            "SELECT id, time, type, parent AS parent_id, text_norm, state,"
            " fetched_at FROM ctx ORDER BY id"
        ).to_arrow_reader(),
        contracts.CONTEXT,
        out_dir / "context.parquet",
    )

    cov = Counter()
    for dim, rows in meta.items():  # shard-meta state/type counters
        for key, count in rows.items():
            cov[("state" if dim == "state" else "type", key)] += count
    for dim, col, where in (
        ("exclusion_reason", "COALESCE(exclusion_reason, 'eligible')", ""),
        ("period", "period", "WHERE period IS NOT NULL"),
        ("month", "month", "WHERE month IS NOT NULL"),
        ("thread_type", "thread_type", ""),
    ):
        q = (
            f"SELECT {col}, COUNT(*) FROM comments_final {where} "
            "GROUP BY 1"
        )
        for key, count in con.execute(q).fetchall():
            cov[(dim, key)] += count
    unresolved = con.execute(
        "SELECT COUNT(*) FROM comments_final WHERE story_id IS NULL"
    ).fetchone()[0]
    cov[("unresolved_root", "comments")] += unresolved
    cov[("unresolved_root", "missing_parents")] += missing_count
    rows = sorted((d, k, v) for (d, k), v in cov.items())
    n_cov = _write_parquet(
        pa.Table.from_pylist(
            [{"dimension": d, "key": k, "count": v} for d, k, v in rows],
            schema=contracts.COVERAGE,
        ).to_batches(),
        contracts.COVERAGE,
        out_dir / "coverage.parquet",
    )

    stats = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(eligible::INT),0) FROM ("
        "SELECT (exclusion_reason IS NULL) eligible FROM comments_final)"
    ).fetchone()
    reasons = {
        r[0]: r[1]
        for r in con.execute(
            "SELECT exclusion_reason, COUNT(*) FROM comments_final"
            " WHERE exclusion_reason IS NOT NULL GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }
    return {
        "comments": n_comments,
        "stories": n_stories,
        "context": n_context,
        "coverage": n_cov,
        "eligible": int(stats[1]),
        "unresolved": int(unresolved),
        "reasons": reasons,
    }

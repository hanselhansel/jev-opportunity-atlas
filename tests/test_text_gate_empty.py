import pyarrow as pa
import pyarrow.parquet as pq

from atlas.publication.allowlist import text_gate


def test_all_null_string_column_does_not_crash(tmp_path):
    pq.write_table(pa.table({"id": [1, 2], "note": pa.array([None, None], type=pa.string())}), tmp_path / "t.parquet")
    assert text_gate(tmp_path) == []

import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.sitedata import source
from atlas.sitedata.tables import SITE_TABLES, write_fixtures


def test_production_without_data_raises(monkeypatch):
    monkeypatch.delenv("ATLAS_SITE_DATA", raising=False)
    monkeypatch.setenv("ATLAS_SITE_MODE", "production")
    with pytest.raises(source.SiteModeError):
        source.resolve()


def test_production_with_fixture_data_raises(monkeypatch, tmp_path):
    write_fixtures(tmp_path, seed=0)
    monkeypatch.setenv("ATLAS_SITE_DATA", str(tmp_path))
    monkeypatch.setenv("ATLAS_SITE_MODE", "production")
    with pytest.raises(source.SiteModeError):
        source.resolve()


def test_production_with_real_data_returns_dir(monkeypatch, tmp_path):
    write_fixtures(tmp_path, seed=0)
    meta = pq.read_table(tmp_path / "meta.parquet").to_pydict()
    meta["value"][meta["key"].index("mode")] = "real"
    real_meta = pa.Table.from_pydict(meta, schema=SITE_TABLES["meta"])
    pq.write_table(real_meta, tmp_path / "meta.parquet")
    monkeypatch.setenv("ATLAS_SITE_DATA", str(tmp_path))
    monkeypatch.setenv("ATLAS_SITE_MODE", "production")
    assert source.resolve() == tmp_path


def test_no_data_no_mode_is_fixture(monkeypatch):
    monkeypatch.delenv("ATLAS_SITE_DATA", raising=False)
    monkeypatch.delenv("ATLAS_SITE_MODE", raising=False)
    assert source.resolve() is None


def test_emit_fixture_mode_writes_parquet_to_buffer(monkeypatch):
    monkeypatch.delenv("ATLAS_SITE_DATA", raising=False)
    monkeypatch.delenv("ATLAS_SITE_MODE", raising=False)
    buf = io.BytesIO()
    source.emit("meta", buf)
    buf.seek(0)
    meta = dict(zip(*pq.read_table(buf).to_pydict().values()))
    assert meta["mode"] == "fixture"


def test_emit_reads_data_dir(monkeypatch, tmp_path):
    write_fixtures(tmp_path, seed=0)
    monkeypatch.setenv("ATLAS_SITE_DATA", str(tmp_path))
    monkeypatch.delenv("ATLAS_SITE_MODE", raising=False)
    buf = io.BytesIO()
    source.emit("runs", buf)
    buf.seek(0)
    assert pq.read_table(buf).num_rows == 4


def test_clear_cache_drops_loader_outputs_keeps_deps(tmp_path):
    cache = tmp_path / "src" / ".observablehq" / "cache"
    (cache / "data").mkdir(parents=True)
    (cache / "data" / "x.parquet").write_bytes(b"x")
    for keep in ("_npm", "_node", "_jsr"):
        (cache / keep).mkdir()
        (cache / keep / "y").write_bytes(b"y")
    source.clear_cache(tmp_path)
    assert not (cache / "data" / "x.parquet").exists()
    for keep in ("_npm", "_node", "_jsr"):
        assert (cache / keep / "y").exists()


def test_clear_cache_missing_dir_is_noop(tmp_path):
    source.clear_cache(tmp_path)


def test_prebuild_production_fails_without_data(monkeypatch, capsys):
    monkeypatch.delenv("ATLAS_SITE_DATA", raising=False)
    monkeypatch.setenv("ATLAS_SITE_MODE", "production")
    assert source.main(["prebuild"]) == 1
    assert "production" in capsys.readouterr().err

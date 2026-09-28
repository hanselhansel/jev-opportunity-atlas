import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths


@pytest.fixture
def repo(tmp_path, monkeypatch):
    snap = tmp_path / "snapshots" / "snap1"
    snap.mkdir(parents=True)
    stories = pa.table(
        {
            "id": [9_000_000_100, 9_000_000_200, 9_000_000_300],
            "descendants": [10, 100, 900],
        }
    )
    ids = list(range(9_000_000_001, 9_000_000_014))
    comments = pa.table(
        {
            "id": ids,
            "story_id": [9_000_000_100] * 4
            + [9_000_000_200] * 4
            + [9_000_000_300] * 4
            + [None],
            "period": ["P01"] * 8 + ["P02"] * 4 + ["P03"],
            "thread_type": ["story"] * 4 + ["ask_hn"] * 4 + ["show_hn"] * 4 + ["story"],
            "eligible": [True] * 12 + [False],
        }
    )
    pq.write_table(comments, snap / "comments.parquet")
    pq.write_table(stories, snap / "stories.parquet")
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "acquisition.toml").write_text('snapshot_id = "snap1"\n')
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "data" / "samples")
    monkeypatch.setattr(paths, "MANIFESTS", tmp_path / "manifests")
    monkeypatch.setattr(paths, "CONFIGS", configs)
    return tmp_path


def run_cli(*argv):
    args = cli.build_parser().parse_args(list(argv))
    args.func(args)


def test_draw_expand_show(repo, capsys):
    samples = paths.SAMPLES
    run_cli("sample", "draw", "--n", "6", "--seed", "11", "--sample-id", "s1")
    out = json.loads(capsys.readouterr().out)
    assert out["sample_id"] == "s1" and out["n"] == 6
    assert (samples / "s1.parquet").exists()
    assert (samples / "s1.json").exists()
    assert (paths.MANIFESTS / "samples" / "s1.json").exists()
    sha1 = hashlib.sha256((samples / "s1.parquet").read_bytes()).hexdigest()

    # Same draw parameters return the stored file untouched.
    run_cli("sample", "draw", "--n", "6", "--seed", "11", "--sample-id", "s1")
    capsys.readouterr()
    assert hashlib.sha256((samples / "s1.parquet").read_bytes()).hexdigest() == sha1

    # Different parameters refuse to overwrite.
    with pytest.raises(Exception, match="different draw parameters"):
        run_cli("sample", "draw", "--n", "4", "--seed", "11", "--sample-id", "s1")

    run_cli("sample", "expand", "--sample-id", "s1", "--extra", "3", "--seed", "12")
    capsys.readouterr()
    assert (samples / "s1-b2.parquet").exists()
    assert (samples / "s1-b2.json").exists()
    assert (paths.MANIFESTS / "samples" / "s1-b2.json").exists()
    meta = json.loads((samples / "s1-b2.json").read_text())
    assert meta["seeds_by_batch"] == {"1": 11, "2": 12}
    assert meta["parent_sample_id"] == "s1"

    with pytest.raises(SystemExit):
        run_cli("sample", "expand", "--sample-id", "s1", "--extra", "3", "--seed", "12")

    run_cli("sample", "show", "--sample-id", "s1")
    shown = capsys.readouterr().out
    assert "total" in shown
    assert "P01|story|e1" in shown

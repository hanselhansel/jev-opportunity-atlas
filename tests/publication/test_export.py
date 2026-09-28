import argparse
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.publication import cli as pubcli
from atlas.publication.allowlist import scan_release
from atlas.publication.export import (
    ExportError,
    chunk_large_files,
    stage_release,
    verify_release,
)

CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64


def make_workspace(tmp_path):
    snap = tmp_path / "data" / "snapshots" / "s1"
    snap.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "id": [9_000_000_001, 9_000_000_002],
                "text_norm": ["a", "b"],
                "author": ["u1", "u2"],
                "text_html": ["a", "b"],
                "text_sha256": ["h1", "h2"],
                "eligible": [True, False],
            }
        ),
        snap / "comments.parquet",
    )
    (snap / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "snapshot_id": "s1"})
    )
    run = tmp_path / "runs" / "r1"
    (run / "answers").mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "comment_id": [9_000_000_001],
                "question_id": ["q"],
                "noul": [0.5],
                "probabilities_json": [
                    json.dumps({f"option_{i}": 0.1 for i in range(8)})
                ],
            }
        ),
        run / "answers" / "part-0.parquet",
    )
    (run / "ledger.jsonl").write_text('{"run_id": "r1", "cost_usd": 0.1}\n')
    (run / "debug.log").write_text("anything")
    return tmp_path


def test_stage_strips_text_and_authors_and_skips_unlisted(tmp_path):
    make_workspace(tmp_path)
    final = stage_release(tmp_path, "v0-test", "s1", ["r1"])
    assert final == tmp_path / "exports" / "v0-test"
    cols = set(pq.read_table(final / "snapshot" / "comments_public.parquet").column_names)
    assert cols == {"id", "text_sha256", "eligible"}
    assert (final / "runs" / "r1" / "ledger.jsonl").exists()
    assert not (final / "runs" / "r1" / "debug.log").exists()
    sums = (final / "SHA256SUMS").read_text()
    assert "runs/r1/ledger.jsonl" in sums
    manifest = json.loads((final / "release_manifest.json").read_text())
    assert manifest["release"] == "v0-test"
    assert manifest["contains_hn_text"] is False
    assert manifest["schema_version"] == 1
    assert manifest["run_ids"] == ["r1"]
    assert (final / "snapshot" / "manifest.json").exists()
    assert not (tmp_path / "exports" / "v0-test.tmp").exists()


def test_secret_in_any_staged_file_blocks(tmp_path):
    make_workspace(tmp_path)
    (tmp_path / "runs" / "r1" / "ledger.jsonl").write_text(
        json.dumps({"note": CANARY}) + "\n"
    )
    with pytest.raises(ExportError) as exc:
        stage_release(tmp_path, "v0-test", "s1", ["r1"])
    assert "typesafe-api-key" in str(exc.value)
    assert CANARY not in str(exc.value)
    assert not (tmp_path / "exports" / "v0-test").exists()


def test_scan_detects_secret_in_parquet_column(tmp_path):
    make_workspace(tmp_path)
    target = tmp_path / "runs" / "r1" / "answers" / "part-1.parquet"
    pq.write_table(
        pa.table(
            {"comment_id": [9_000_000_001], "model_returned": [CANARY]}
        ),
        target,
        compression="zstd",
    )
    with pytest.raises(ExportError) as exc:
        stage_release(tmp_path, "v0-test", "s1", ["r1"])
    assert "typesafe-api-key" in str(exc.value)
    assert "part-1.parquet" in str(exc.value)
    assert CANARY not in str(exc.value)


def test_scan_release_decodes_zst_stream(tmp_path):
    import zstandard

    payload = ('{"note": "' + CANARY + '"}\n').encode()
    (tmp_path / "x.jsonl.zst").write_bytes(
        zstandard.ZstdCompressor().compress(payload)
    )
    findings = scan_release(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule == "typesafe-api-key"
    assert findings[0].path == "x.jsonl.zst"


def test_stage_rejects_text_like_json(tmp_path):
    make_workspace(tmp_path)
    (tmp_path / "runs" / "r1" / "eval_heldout.json").write_text(
        json.dumps(
            {"errors": [{"comment_id": 9_000_000_001, "text": "synthetic"}]}
        )
    )
    with pytest.raises(ExportError) as exc:
        stage_release(tmp_path, "v0-test", "s1", ["r1"])
    msg = str(exc.value)
    assert "forbidden-field" in msg
    assert "eval_heldout.json" in msg
    assert "text" in msg
    assert "synthetic" not in msg


def test_stage_rejects_title_column(tmp_path):
    make_workspace(tmp_path)
    pq.write_table(
        pa.table({"comment_id": [9_000_000_001], "title": ["synthetic"]}),
        tmp_path / "runs" / "r1" / "answers" / "part-2.parquet",
    )
    with pytest.raises(ExportError) as exc:
        stage_release(tmp_path, "v0-test", "s1", ["r1"])
    assert "title" in str(exc.value)


def test_stage_rejects_long_string_column(tmp_path):
    make_workspace(tmp_path)
    pq.write_table(
        pa.table(
            {"comment_id": [9_000_000_001] * 3, "note": ["x" * 120] * 3}
        ),
        tmp_path / "runs" / "r1" / "answers" / "part-3.parquet",
    )
    with pytest.raises(ExportError) as exc:
        stage_release(tmp_path, "v0-test", "s1", ["r1"])
    assert "long-strings" in str(exc.value)
    assert "note" in str(exc.value)
    assert "x" * 120 not in str(exc.value)


def test_stage_refuses_existing_release(tmp_path):
    make_workspace(tmp_path)
    stage_release(tmp_path, "v0-test", "s1", ["r1"])
    with pytest.raises(ExportError):
        stage_release(tmp_path, "v0-test", "s1", ["r1"])


def test_stage_includes_reproducibility_inputs(tmp_path):
    make_workspace(tmp_path)
    samples = tmp_path / "data" / "samples"
    samples.mkdir(parents=True)
    pq.write_table(
        pa.table({"sample_id": ["smp"], "comment_id": [9_000_000_001]}),
        samples / "smp.parquet",
    )
    (samples / "smp.json").write_text('{"sample_id": "smp"}')
    labels = tmp_path / "data" / "labels"
    labels.mkdir(parents=True)
    row = {
        "label_id": "l1",
        "comment_id": 9_000_000_001,
        "label_set": "calibration",
        "question_id": "q",
        "value": "no",
        "rubric_version": "v1",
        "reviewer": "r1x",
        "started_at": "t",
        "ended_at": "t",
        "seconds": 1.0,
    }
    latest = dict(row, value="yes")
    (labels / "labels.jsonl").write_text(
        json.dumps(row) + "\n" + json.dumps(latest) + "\n"
    )
    questions = tmp_path / "configs" / "questions"
    questions.mkdir(parents=True)
    (questions / "screen.v0.json").write_text(
        json.dumps({"instructions": "i" * 150})
    )
    (tmp_path / "configs" / "rubric.v1.md").write_text("rubric")
    (tmp_path / "configs" / "prices.toml").write_text("[p]\n")
    (tmp_path / "configs" / "budgets.toml").write_text("[b]\n")
    man = tmp_path / "manifests" / "samples"
    man.mkdir(parents=True)
    (man / "smp.json").write_text("{}")
    (tmp_path / "claims").mkdir()
    (tmp_path / "claims" / "claims.yaml").write_text("[]\n")
    (tmp_path / "taxonomy").mkdir()
    (tmp_path / "taxonomy" / "x.json").write_text("{}")

    final = stage_release(tmp_path, "v0-test", "s1", ["r1"])
    for rel in (
        "snapshot/comments_public.parquet",
        "snapshot/manifest.json",
        "runs/r1/answers/part-0.parquet",
        "runs/r1/ledger.jsonl",
        "samples/smp.parquet",
        "samples/smp.json",
        "labels/labels_public.parquet",
        "manifests/samples/smp.json",
        "claims/claims.yaml",
        "configs/questions/screen.v0.json",
        "configs/rubric.v1.md",
        "configs/prices.toml",
        "configs/budgets.toml",
    ):
        assert (final / rel).exists(), rel
    assert not (final / "taxonomy" / "x.json").exists()
    table = pq.read_table(final / "labels" / "labels_public.parquet")
    assert table.num_rows == 1
    assert "reviewer" not in table.column_names
    assert table.column("value").to_pylist() == ["yes"]


def test_chunk_large_files_splits_and_removes_original(tmp_path):
    data = bytes(range(256)) * 10
    (tmp_path / "big.bin").write_bytes(data[:2500])
    (tmp_path / "small.txt").write_text("s")
    chunks = chunk_large_files(tmp_path, limit=1000)
    assert chunks == {
        "big.bin": ["big.bin.part000", "big.bin.part001", "big.bin.part002"]
    }
    assert not (tmp_path / "big.bin").exists()
    rebuilt = b"".join((tmp_path / p).read_bytes() for p in chunks["big.bin"])
    assert rebuilt == data[:2500]
    assert (tmp_path / "small.txt").read_text() == "s"


def test_verify_release_detects_tamper_and_missing(tmp_path):
    make_workspace(tmp_path)
    final = stage_release(tmp_path, "v0-test", "s1", ["r1"])
    assert verify_release(final)["ok"] is True
    ledger = final / "runs" / "r1" / "ledger.jsonl"
    ledger.write_text('{"run_id": "r1", "cost_usd": 9.9}\n')
    result = verify_release(final)
    assert result["ok"] is False
    assert result["bad"] == ["runs/r1/ledger.jsonl"]
    (final / "snapshot" / "manifest.json").unlink()
    result = verify_release(final)
    assert "snapshot/manifest.json" in result["missing"]
    (final / "stray.txt").write_text("stray")
    result = verify_release(final)
    assert "stray.txt" in result["extra"]


def test_release_stage_and_check_cli(tmp_path, monkeypatch):
    make_workspace(tmp_path)
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "EXPORTS", tmp_path / "exports")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    pubcli.register(sub)
    args = parser.parse_args(
        [
            "release",
            "stage",
            "--release",
            "v0-cli",
            "--snapshot",
            "s1",
            "--run",
            "r1",
        ]
    )
    args.func(args)
    args = parser.parse_args(["release", "check", "--release", "v0-cli"])
    args.func(args)
    ledger = tmp_path / "exports" / "v0-cli" / "runs" / "r1" / "ledger.jsonl"
    ledger.write_text('{"run_id": "r1", "cost_usd": 9.9}\n')
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == 1

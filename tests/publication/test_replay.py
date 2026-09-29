import argparse
import shutil
import subprocess
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest
import yaml

from atlas.publication.export import stage_release
from atlas.publication.replay import replay
from atlas.publication.restore import add_site_tables, pack_release, restore
from atlas.sitedata.tables import SITE_TABLES
from tests.publication.test_export import make_workspace
from tests.publication.test_restore import clean_site_tables, gh_transport

REPO = Path(__file__).resolve().parents[2]

CLAIM = {
    "text": "Rows in the runs table.",
    "tolerance": 0,
    "sql": "SELECT count(*) FROM read_parquet('{root}/site/runs.parquet')",
    "run_id": "fixture-run",
    "lane": "breadth",
    "denominator": "runs table rows",
    "question_set": "fixture@0",
    "weighted": False,
    "ci_low": None,
    "ci_high": None,
    "qualifier": "fixture",
}


def block_network(monkeypatch):
    """Applied after the restore (which uses a mock transport), before replay."""

    def refuse(self, request, *args, **kwargs):
        raise AssertionError(f"network call during replay: {request.url}")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)


def restored_release(tmp_path, claims):
    ws = make_workspace(tmp_path / "ws")
    (ws / "claims").mkdir()
    (ws / "claims" / "claims.yaml").write_text(yaml.safe_dump(claims))
    rel = stage_release(ws, "v1-replay", "s1", ["r1"])
    add_site_tables(rel, clean_site_tables(tmp_path / "sitedata"))
    assets = tmp_path / "assets"
    pack_release(rel, assets)
    restore("v1-replay", tmp_path / "r", transport=gh_transport(assets, "v1-replay"))
    return tmp_path / "r" / "v1-replay"


def test_replay_passes_claims_and_builds_site_data(tmp_path, monkeypatch):
    rows = pq.read_metadata(
        clean_site_tables(tmp_path / "probe") / "runs.parquet"
    ).num_rows
    rel = restored_release(tmp_path, [{**CLAIM, "id": "runs_rows", "value": rows}])
    block_network(monkeypatch)
    out = tmp_path / "site-data"
    report = replay(rel, site_out=out)
    assert report["ok"] is True
    assert report["verify"]["ok"] is True
    assert report["claims"] == {"runs_rows": "pass"}
    assert sorted(p.stem for p in out.glob("*.parquet")) == sorted(SITE_TABLES)
    assert report["site_data"] == str(out)


def test_replay_reports_failing_claim(tmp_path, monkeypatch):
    rel = restored_release(
        tmp_path,
        [
            {**CLAIM, "id": "good", "value": 4},
            {**CLAIM, "id": "stale", "value": 999},
            {
                **CLAIM,
                "id": "needs_full",
                "value": 1,
                "sql": "SELECT count(*) FROM read_parquet('{root}/runs/r1/answers/*.parquet')",
            },
        ],
    )
    block_network(monkeypatch)
    report = replay(rel, site_out=tmp_path / "sd")
    assert report["ok"] is False
    assert report["claims"]["stale"] == "fail"
    assert report["claims"]["needs_full"] == "fail"
    assert "999" in report["claim_errors"]["stale"]


def test_replay_stops_on_tampered_release(tmp_path, monkeypatch):
    rel = restored_release(tmp_path, [])
    block_network(monkeypatch)
    (rel / "site" / "meta.parquet").write_bytes(b"tampered")
    report = replay(rel, site_out=tmp_path / "sd")
    assert report["ok"] is False
    assert report["verify"]["bad"] == ["site/meta.parquet"]
    assert report["claims"] == {}
    assert not (tmp_path / "sd").exists()


def test_cli_replay_exit_code(tmp_path, monkeypatch, capsys):
    from atlas.publication import cli as pubcli

    rel = restored_release(tmp_path, [{**CLAIM, "id": "stale", "value": 999}])
    block_network(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        pubcli._release_replay(
            argparse.Namespace(release_dir=str(rel), site_out=str(tmp_path / "sd"))
        )
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "verify: ok" in out
    assert "claim stale: fail" in out
    assert "replay: FAIL" in out


def test_replay_script_is_valid_shell():
    script = REPO / "scripts" / "replay.sh"
    assert subprocess.run(["sh", "-n", str(script)], check=False).returncode == 0
    text = script.read_text()
    assert "uv sync --no-default-groups" in text
    assert "atlas release restore" in text and "atlas release replay" in text
    assert "npm ci" in text


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
def test_replay_script_usage_without_tag():
    script = REPO / "scripts" / "replay.sh"
    r = subprocess.run(["sh", str(script)], capture_output=True, check=False)
    assert r.returncode == 2
    assert b"usage" in r.stdout + r.stderr

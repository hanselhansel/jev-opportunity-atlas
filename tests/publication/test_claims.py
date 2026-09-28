import argparse
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.publication import cli as pubcli
from atlas.publication.claims import check_claims, load_claims


def claim(**over):
    c = {
        "id": "c1",
        "text": "half of comments are firsthand",
        "value": 0.5,
        "tolerance": 0.001,
        "sql": "SELECT avg(firsthand) FROM read_parquet('{root}/t.parquet')",
        "run_id": "r1",
        "lane": "breadth",
        "denominator": "screened comments, unweighted count",
        "question_set": "screen@0",
        "weighted": False,
        "ci_low": 0.4,
        "ci_high": 0.6,
        "qualifier": "synthetic",
    }
    c.update(over)
    return c


@pytest.fixture
def answers_parquet(tmp_path):
    pq.write_table(
        pa.table(
            {
                "comment_id": [
                    9_000_000_001,
                    9_000_000_002,
                    9_000_000_003,
                    9_000_000_004,
                ],
                "firsthand": [1, 1, 0, 0],
            }
        ),
        tmp_path / "t.parquet",
    )
    return tmp_path


def test_claim_matches_and_drift_fails(answers_parquet):
    results = check_claims([claim(), claim(id="c2", value=0.9)], answers_parquet)
    assert results["c1"]["ok"] is True
    assert results["c2"]["ok"] is False
    assert results["c2"]["actual"] == 0.5


def test_required_fields_enforced(tmp_path):
    results = check_claims(
        [{"id": "c3", "text": "x", "value": 1, "sql": "SELECT 1"}], tmp_path
    )
    assert results["c3"]["ok"] is False
    assert "missing" in results["c3"]["error"]


def test_unweighted_breadth_proportion_needs_unweighted_denominator(
    answers_parquet,
):
    bad = claim(denominator="screened comments")
    results = check_claims([bad], answers_parquet)
    assert results["c1"]["ok"] is False
    assert "unweighted" in results["c1"]["error"]
    ok_weighted = claim(denominator="screened comments", weighted=True)
    assert check_claims([ok_weighted], answers_parquet)["c1"]["ok"] is True
    discovery = claim(denominator="screened comments", lane="discovery")
    assert check_claims([discovery], answers_parquet)["c1"]["ok"] is True


def test_ci_null_only_for_counts(answers_parquet):
    proportion = claim(ci_low=None)
    results = check_claims([proportion], answers_parquet)
    assert results["c1"]["ok"] is False
    assert "ci_low" in results["c1"]["error"]
    count = claim(
        value=2,
        sql="SELECT sum(firsthand) FROM read_parquet('{root}/t.parquet')",
        ci_low=None,
        ci_high=None,
    )
    results = check_claims([count], answers_parquet)
    assert results["c1"]["ok"] is True


def test_root_uses_replace_not_format(answers_parquet):
    c = claim(
        sql=(
            "SELECT struct_extract({'v': avg(firsthand)}, 'v') "
            "FROM read_parquet('{root}/t.parquet')"
        )
    )
    results = check_claims([c], answers_parquet)
    assert results["c1"]["ok"] is True


def test_non_scalar_result_fails(answers_parquet):
    c = claim(value=1, sql="SELECT 1, 2")
    results = check_claims([c], answers_parquet)
    assert results["c1"]["ok"] is False
    assert "single scalar" in results["c1"]["error"]


def test_repo_claims_file_loads():
    repo = Path(__file__).resolve().parents[2]
    assert load_claims(repo / "claims" / "claims.yaml") == []


def test_claims_check_cli_exit_codes(tmp_path, monkeypatch, answers_parquet):
    monkeypatch.setattr(paths, "ROOT", answers_parquet)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    pubcli.register(sub)
    good = tmp_path / "claims_ok.yaml"
    good.write_text(json.dumps([claim()]))
    args = parser.parse_args(["claims", "check", "--file", str(good)])
    args.func(args)
    bad = tmp_path / "claims_bad.yaml"
    bad.write_text(json.dumps([claim(value=0.9)]))
    args = parser.parse_args(["claims", "check", "--file", str(bad)])
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == 1

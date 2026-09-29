"""The ``robustness`` table: how the headline numbers move under reworded
questions, built from the JSON outputs of ``robust compare-screen`` and
``robust compare-assign``.
"""

from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from atlas.sitedata.build_robustness import robustness_rows
from atlas.sitedata.tables import SITE_TABLES
from tests.sitedata.world import build, build_world, read

# Shaped exactly like atlas.robustness.compare.compare_screen output.
SCREEN_JSON = {
    "main_run": "screen-main",
    "sample_id": "rob-sub",
    "cutoff": 0.7,
    "n_sample": 8,
    "runs": {
        "screen-main": {
            "n": 8,
            "prevalence": 0.5,
            "ci_low": 0.3,
            "ci_high": 0.7,
        },
        "screen-para-1": {
            "n": 8,
            "prevalence": 0.4,
            "ci_low": 0.2,
            "ci_high": 0.6,
            "vs_main": {"n": 8, "agreement": 0.75, "kappa": 0.5, "spearman": 0.9},
        },
        "screen-para-2": {
            "n": 8,
            "prevalence": 0.45,
            "ci_low": 0.25,
            "ci_high": 0.65,
            "vs_main": {"n": 8, "agreement": 0.875, "kappa": 0.6, "spearman": 0.8},
        },
    },
}
# Shaped exactly like atlas.robustness.compare.compare_assign output.
ASSIGN_JSON = {
    "main_run": "assign-main",
    "version": "t9",
    "n_main": 10,
    "runs": {
        "assign-para-1": {
            "n": 12,
            "n_common": 10,
            "group_agreement": 0.8,
            "card_agreement": 0.6,
            "card_shares": {
                "c01": {"main": 0.2, "run": 0.25, "abs_diff": 0.05},
                "c02": {"main": 0.1, "run": 0.08, "abs_diff": 0.02},
            },
            "max_abs_diff": 0.05,
        }
    },
}


def _row(check, run_id, metric, value, lo=None, hi=None, n=None):
    return {
        "check": check,
        "run_id": run_id,
        "metric": metric,
        "value": value,
        "lo": lo,
        "hi": hi,
        "n": n,
    }


def test_schema_is_in_site_tables():
    assert SITE_TABLES["robustness"].names == [
        "check",
        "run_id",
        "metric",
        "value",
        "lo",
        "hi",
        "n",
    ]


def test_screen_rows_carry_prevalence_and_agreement_metrics():
    rows = robustness_rows(screen=SCREEN_JSON)
    expected = [
        _row("screen_wording", "screen-main", "prevalence", 0.5, 0.3, 0.7, 8),
        _row("screen_wording", "screen-para-1", "prevalence", 0.4, 0.2, 0.6, 8),
        _row("screen_wording", "screen-para-1", "agreement", 0.75, n=8),
        _row("screen_wording", "screen-para-1", "kappa", 0.5, n=8),
        _row("screen_wording", "screen-para-1", "spearman", 0.9, n=8),
        _row("screen_wording", "screen-para-2", "prevalence", 0.45, 0.25, 0.65, 8),
        _row("screen_wording", "screen-para-2", "agreement", 0.875, n=8),
        _row("screen_wording", "screen-para-2", "kappa", 0.6, n=8),
        _row("screen_wording", "screen-para-2", "spearman", 0.8, n=8),
    ]
    assert rows == expected


def test_assign_rows_carry_agreements_and_max_share_diff():
    rows = robustness_rows(assign=ASSIGN_JSON)
    expected = [
        _row("assign_wording", "assign-para-1", "group_agreement", 0.8, n=10),
        _row("assign_wording", "assign-para-1", "card_agreement", 0.6, n=10),
        _row("assign_wording", "assign-para-1", "max_abs_share_diff", 0.05, n=12),
    ]
    assert rows == expected


def test_no_inputs_gives_no_rows():
    assert robustness_rows() == []
    assert robustness_rows(screen=None, assign=None) == []
    assert robustness_rows(screen={}, assign={}) == []


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def test_build_writes_an_empty_table_without_robustness_inputs(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    t = pq.read_table(out / "robustness.parquet")
    assert t.schema.equals(SITE_TABLES["robustness"])
    assert t.num_rows == 0


def test_build_writes_robustness_rows_from_json_files(world, tmp_path):
    screen_path = tmp_path / "compare-screen.json"
    assign_path = tmp_path / "compare-assign.json"
    screen_path.write_text(json.dumps(SCREEN_JSON))
    assign_path.write_text(json.dumps(ASSIGN_JSON))
    out = tmp_path / "site-real"
    build(
        out,
        robust_screen=str(screen_path),
        robust_assign=str(assign_path),
    )
    rows = read(out, "robustness")
    assert len(rows) == 12
    main = next(
        r
        for r in rows
        if r["check"] == "screen_wording"
        and r["run_id"] == "screen-main"
        and r["metric"] == "prevalence"
    )
    assert main["value"] == 0.5 and main["lo"] == 0.3 and main["hi"] == 0.7
    diff = next(r for r in rows if r["metric"] == "max_abs_share_diff")
    assert diff["value"] == 0.05 and diff["n"] == 12


def test_site_data_cli_accepts_robustness_flags(world, tmp_path, capsys):
    from atlas import cli as atlas_cli

    screen_path = tmp_path / "compare-screen.json"
    screen_path.write_text(json.dumps(SCREEN_JSON))
    out = tmp_path / "data-real"
    args = atlas_cli.build_parser().parse_args(
        [
            "site", "data", "--out", str(out), "--snapshot", "snap-syn",
            "--screen-run", "screen-syn", "--facets-run", "facets-syn",
            "--assign-run", "assign-syn", "--taxonomy", "t9",
            "--facet-sample", "facet-syn",
            "--robust-screen", str(screen_path),
            "--n-boot", "50",
        ]
    )
    args.func(args)
    rows = read(out, "robustness")
    assert {r["check"] for r in rows} == {"screen_wording"}
    assert json.loads(capsys.readouterr().out)["robustness"] == 9


def test_fixtures_include_robustness_rows():
    from atlas.sitedata.fixtures import fixture_tables

    rows = fixture_tables(0)["robustness"].to_pylist()
    assert rows
    checks = {r["check"] for r in rows}
    assert checks <= {"screen_wording", "assign_wording"}
    assert "screen_wording" in checks
    prev = [r for r in rows if r["metric"] == "prevalence"]
    assert prev and all(
        r["lo"] <= r["value"] <= r["hi"] for r in prev
    )

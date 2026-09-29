"""L32: full-spend runs from a phase map, audit runs, weighted finding domains."""

from __future__ import annotations

import json

import numpy as np
import pytest

from atlas import paths
from tests.sitedata.world import _ledger, build, build_world, read


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def _phases(tmp_path, text: str) -> str:
    p = tmp_path / "phases.toml"
    p.write_text(text)
    return str(p)


def test_run_phases_builds_runs_from_every_key(world, tmp_path):
    _ledger(
        paths.run_dir("deep/nested"),
        "deep/nested",
        "qs",
        3,
        np.random.default_rng(1),
    )
    phases = _phases(
        tmp_path,
        "[runs]\n"
        '"screen-syn" = "screen"\n'
        '"deep/nested" = "extra phase"\n'
        '"assign-syn" = "assign"\n',
    )
    out = tmp_path / "site-real"
    build(out, run_phases=phases)
    runs = {r["run_id"]: r for r in read(out, "runs")}
    assert set(runs) == {"screen-syn", "deep/nested", "assign-syn"}
    assert runs["deep/nested"]["phase"] == "extra phase"
    assert runs["deep/nested"]["calls"] == 3
    assert runs["screen-syn"]["phase"] == "screen"
    meta = {r["key"]: r["value"] for r in read(out, "meta")}
    assert float(meta["total_calculated_usd"]) == pytest.approx(
        sum(r["calculated_usd"] for r in runs.values())
    )
    assert int(meta["total_calls"]) == sum(r["calls"] for r in runs.values())


def test_run_phases_missing_ledger_names_the_key(world, tmp_path):
    from atlas.sitedata.build import SiteDataError

    phases = _phases(
        tmp_path, '[runs]\n"screen-syn" = "screen"\n"gone/run" = "checks"\n'
    )
    with pytest.raises(SiteDataError, match="gone/run"):
        build(tmp_path / "site-real", run_phases=phases)


def test_runs_without_run_phases_come_from_roles(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    assert {r["run_id"] for r in read(out, "runs")} == {
        "screen-syn",
        "facets-syn",
        "assign-syn",
        "bench-syn",
    }


def test_site_data_cli_run_phases_and_audit_run(world, tmp_path, capsys):
    from atlas import cli as atlas_cli

    audit = paths.run_dir("audit-syn")
    audit.mkdir(parents=True)
    (audit / "eval_assignment_audit.json").write_text(json.dumps(ASSIGNMENT_AUDIT))
    phases = _phases(
        tmp_path,
        "[runs]\n"
        '"screen-syn" = "screen"\n'
        '"facets-syn" = "facets"\n'
        '"assign-syn" = "assign"\n'
        '"bench-syn" = "checks"\n',
    )
    out = tmp_path / "site-real"
    args = atlas_cli.build_parser().parse_args(
        [
            "site", "data", "--out", str(out), "--snapshot", "snap-syn",
            "--screen-run", "screen-syn", "--facets-run", "facets-syn",
            "--assign-run", "assign-syn", "--taxonomy", "t9",
            "--facet-sample", "facet-syn", "--label-set", "calibration",
            "--benchmark-run", "bench-syn", "--run-phases", phases,
            "--audit-run", "audit-syn", "--n-boot", "50",
        ]
    )
    args.func(args)
    assert {r["run_id"] for r in read(out, "runs")} == {
        "screen-syn",
        "facets-syn",
        "assign-syn",
        "bench-syn",
    }
    meta = {r["key"]: r["value"] for r in read(out, "meta")}
    assert int(meta["total_calls"]) == 120 + 80 + 40 + 20
    assert float(meta["total_calculated_usd"]) == pytest.approx(0.26)


ASSIGNMENT_AUDIT = {
    "label_set": "assignment_audit",
    "groups": {
        "jev": {
            "n": 120,
            "n_unsure": 5,
            "strict": {"precision": 0.95, "ci": [0.9, 0.98]},
            "lenient": {"precision": 0.97, "ci": [0.93, 0.99]},
        },
        "random": {
            "n": 40,
            "n_unsure": 2,
            "strict": {"precision": 0.05, "ci": [0.01, 0.14]},
            "lenient": {"precision": 0.1, "ci": [0.03, 0.22]},
        },
    },
}


def test_audit_run_reports_join_quality(world, tmp_path):
    audit = paths.run_dir("audit-syn")
    audit.mkdir(parents=True)
    (audit / "eval_assignment_audit.json").write_text(json.dumps(ASSIGNMENT_AUDIT))
    out = tmp_path / "site-real"
    build(out, audit_runs=["audit-syn"])
    q = [
        r
        for r in read(out, "quality")
        if r["label_set"] == "assignment_audit"
    ]
    by = {(r["system"], r["metric"]): r for r in q}
    assert len(q) == 4
    assert by[("jev", "precision_strict")]["value"] == 0.95
    assert by[("jev", "precision_strict")]["n"] == 115
    assert by[("jev", "precision_lenient")]["ci_low"] == 0.93
    assert by[("random_card", "precision_strict")]["value"] == 0.05
    assert by[("random_card", "precision_strict")]["ci_high"] == 0.14
    assert by[("random_card", "precision_lenient")]["n"] == 38


def test_finding_domain_is_weighted_modal():
    from atlas.sitedata.build_cards import _top_domain

    ctx = {
        "answers": {
            1: {"domain": {"choice": "data_ml_ai"}},
            2: {"domain": {"choice": "infrastructure_ops"}},
            3: {"domain": {"choice": "infrastructure_ops"}},
        },
        "facet": {1: {"weight": 100.0}, 2: {"weight": 1.0}, 3: {"weight": 1.0}},
    }
    members = [{"comment_id": c} for c in (1, 2, 3)]
    assert _top_domain(members, ctx) == "data_ml_ai"
    tied = {
        "answers": {
            1: {"domain": {"choice": "beta"}},
            2: {"domain": {"choice": "alpha"}},
        },
        "facet": {1: {"weight": 5.0}, 2: {"weight": 5.0}},
    }
    assert _top_domain([{"comment_id": 1}, {"comment_id": 2}], tied) == "alpha"


def test_findings_domain_matches_weighted_mode(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    fe = read(out, "finding_evidence")
    findings = read(out, "findings")
    assert findings
    for f in findings:
        weights: dict[str, float] = {}
        for r in fe:
            if r["finding_id"] != f["finding_id"]:
                continue
            cid = r["comment_id"]
            d = world["domain"][cid]
            weights[d] = weights.get(d, 0.0) + world["facet"][cid]["weight"]
        expected = (
            min(weights, key=lambda d: (-weights[d], d)) if weights else None
        )
        assert f["domain"] == expected


def test_cost_spec_breaks_spend_down_by_phase(world, tmp_path):
    from atlas.sitedata.xspecs import site_chart_specs

    _ledger(
        paths.run_dir("deep/nested"),
        "deep/nested",
        "qs",
        3,
        np.random.default_rng(2),
    )
    phases = _phases(
        tmp_path,
        "[runs]\n"
        '"screen-syn" = "screen"\n'
        '"deep/nested" = "screen"\n'
        '"bench-syn" = "checks"\n',
    )
    out = tmp_path / "site-real"
    build(out, run_phases=phases)
    cost = next(s for s in site_chart_specs(out) if s["kind"] == "cost")
    data = cost["data"]
    assert data["calculated_usd"] == pytest.approx(0.12 + 0.003 + 0.02)
    assert data["calls"] == 120 + 3 + 20
    by_phase = {p["phase"]: p for p in data["phases"]}
    assert by_phase["screen"]["calls"] == 123
    assert by_phase["screen"]["runs"] == 2
    assert by_phase["checks"]["calculated_usd"] == pytest.approx(0.02)
    assert sum(p["calculated_usd"] for p in data["phases"]) == pytest.approx(
        data["calculated_usd"]
    )

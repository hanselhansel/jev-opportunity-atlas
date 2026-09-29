"""L34: every chart footer names the run that produced its numbers.

Card charts (group share, card share, card change, heat, bars) name the
assignment run. The quality chart names the audit runs behind its human-audit
rows and the benchmark run behind its synthetic rows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atlas import paths
from tests.sitedata.test_full_accounting import ASSIGNMENT_AUDIT
from tests.sitedata.world import build, build_world, read

SITE_SRC = Path(__file__).resolve().parents[2] / "site" / "src"
CARD_CHARTS = ("bars", "heat", "group_share", "card_share_top", "card_change")


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def _audit_run():
    audit = paths.run_dir("audit-syn")
    audit.mkdir(parents=True)
    (audit / "eval_assignment_audit.json").write_text(json.dumps(ASSIGNMENT_AUDIT))


def test_card_chart_specs_name_the_assign_run(world, tmp_path):
    from atlas.sitedata.xcharts import footer_text, site_chart_specs

    out = tmp_path / "site-real"
    build(out)
    specs = {s["name"]: s for s in site_chart_specs(out)}
    for name in CARD_CHARTS:
        assert specs[name]["run_id"] == "assign-syn", name
        assert "Run: assign-syn" in footer_text(specs[name]), name


def test_quality_rows_carry_their_source_run(world, tmp_path):
    _audit_run()
    out = tmp_path / "site-real"
    build(out, audit_runs=["audit-syn"])
    q = read(out, "quality")
    audit_rows = [r for r in q if r["label_set"] == "assignment_audit"]
    assert audit_rows and {r.get("run_id") for r in audit_rows} == {"audit-syn"}
    bench = [r for r in q if r["label_set"] == "synthetic"]
    assert bench and {r.get("run_id") for r in bench} == {"bench-syn"}


def test_quality_rows_from_a_role_run_keep_its_run_id(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    q = [r for r in read(out, "quality") if r["label_set"] == "assignment_audit"]
    assert q and {r.get("run_id") for r in q} == {"assign-syn"}


def test_quality_spec_names_audit_and_benchmark_runs(world, tmp_path):
    from atlas.sitedata.xcharts import footer_text, site_chart_specs

    _audit_run()
    out = tmp_path / "site-real"
    build(out, audit_runs=["audit-syn"])
    spec = next(s for s in site_chart_specs(out) if s["kind"] == "quality")
    assert spec["run_id"] == "audit-syn+bench-syn"
    assert "Run: audit-syn+bench-syn" in footer_text(spec)


def test_index_card_charts_pass_the_assign_run():
    src = (SITE_SRC / "index.md").read_text()
    # shareBarChart and changeChart only render card_share data.
    assert src.count("run: meta.assign_run") == 2


def test_chart_component_accepts_a_run_override():
    src = (SITE_SRC / "components" / "chart.js").read_text()
    assert re.search(r"run\s*[,}]", src)
    assert "run ?? meta?.run_id" in src

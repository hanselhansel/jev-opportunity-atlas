"""Display-only short labels from configs/cards/<cardset>.<version>.labels.yaml.

Short labels are Claude-drafted display text for charts; every group and card
without one falls back to the full statement. No label over 32 characters may
reach a chart.
"""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from atlas import paths
from tests.sitedata.world import TV, build, build_world, read

LABELS_YAML = f"""taxonomy_version: {TV}
groups:
  g01: "Group one short"
  g02: "Group two short"
cards:
  c01: "Need one short"
  c02: "Need two short"
  c03: "Need three short"
"""


def _write_labels(text: str = LABELS_YAML):
    (paths.CONFIGS / "cards" / f"syn.{TV}.labels.yaml").write_text(text)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def test_short_labels_in_card_share_and_findings(world, tmp_path):
    _write_labels()
    out = tmp_path / "site-real"
    build(out)
    assert "short_label" in pq.read_schema(out / "card_share.parquet").names
    assert "short_label" in pq.read_schema(out / "findings.parquet").names
    rows = {
        (r["level"], r["id"]): r
        for r in read(out, "card_share")
        if r["population"] == "screen_positive" and r["bucket"] == "all"
    }
    assert rows[("group", "g01")]["short_label"] == "Group one short"
    assert rows[("card", "c01")]["short_label"] == "Need one short"
    # c04 has no short label: it falls back to the full statement.
    c04 = rows[("card", "c04")]
    assert c04["short_label"] == c04["label"] == "Synthetic need four"
    findings = {f["finding_id"]: f for f in read(out, "findings")}
    assert findings["c01"]["short_label"] == "Need one short"


def test_short_labels_fall_back_without_a_labels_file(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    rows = read(out, "card_share")
    assert all(r["short_label"] == r["label"] for r in rows)
    for f in read(out, "findings"):
        assert f["short_label"] == f["title"]


def test_short_labels_pass_the_text_gate(world, tmp_path):
    from atlas.sitedata.build import site_text_problems

    _write_labels()
    out = tmp_path / "site-real"
    build(out)
    assert site_text_problems(out) == []


def test_labels_over_32_chars_are_rejected(world, tmp_path):
    from atlas.sitedata.build import SiteDataError

    _write_labels(LABELS_YAML.replace("Need one short", "x" * 33))
    with pytest.raises(SiteDataError, match="32"):
        build(tmp_path / "site-real")


def test_charts_get_only_short_labels(world, tmp_path):
    from atlas.sitedata.xspecs import site_chart_specs

    _write_labels()
    out = tmp_path / "site-real"
    build(out)
    specs = {s["name"]: s for s in site_chart_specs(out)}
    for name in ("bars", "group_share", "card_share_top", "card_change"):
        for row in specs[name]["data"]["rows"]:
            assert len(row["label"]) <= 32, (name, row["label"])
    for label in specs["heat"]["data"]["rows"]:
        assert len(label) <= 32, label
    first = specs["group_share"]["data"]["rows"][0]
    assert first["label"] in ("Group one short", "Group two short")
    top = specs["card_share_top"]["data"]["rows"][0]
    assert top["label"].endswith("short") or top["label"] == "Synthetic need four"
    # The full statement stays available for tooltips and tables.
    assert top["full_label"].startswith("Synthetic need")

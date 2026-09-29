"""Configured chart titles and run labels from configs/x_titles.toml, plus
title fitting inside the 1600 px canvas."""

from __future__ import annotations

import json

import pytest

from atlas import paths
from tests.sitedata.test_xcharts import png_size, spec
from tests.sitedata.world import build, build_world, read

TITLES_TOML = """
[titles]
bars = "These problems drew the most distinct people on HN."
card_share_top = "No single problem dominates. The biggest holds {top_share} of all complaints."
wording_range = "Rewording moves the headline between {min_share} and {max_share}."
cost = "The atlas cost {total_usd} of Jev credit over {total_calls} calls."
quality = "Jev fit {jev_precision} of audited cards; a random card fit {random_precision}."

[run_labels]
"screen-syn" = "original wording"
"screen-para" = "rewording 1"
"""

ROBUST_SCREEN = {
    "main_run": "screen-syn",
    "sample_id": "sub",
    "cutoff": 0.7,
    "n_sample": 8,
    "runs": {
        "screen-syn": {"n": 8, "prevalence": 0.042, "ci_low": 0.03, "ci_high": 0.06},
        "screen-para": {
            "n": 8,
            "prevalence": 0.116,
            "ci_low": 0.08,
            "ci_high": 0.15,
            "vs_main": {"n": 8, "agreement": 0.9, "kappa": 0.7, "spearman": 0.8},
        },
    },
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def _build(world, tmp_path, toml=TITLES_TOML, **kw):
    (paths.CONFIGS / "x_titles.toml").write_text(toml)
    out = tmp_path / "site-real"
    build(out, **kw)
    return out


def test_titles_fill_placeholders_from_the_data(world, tmp_path):
    out = _build(world, tmp_path)
    from atlas.sitedata.xspecs import site_chart_specs

    specs = {s["name"]: s for s in site_chart_specs(out)}
    top = max(
        r["share"]
        for r in read(out, "card_share")
        if r["level"] == "card"
        and r["population"] == "screen_positive"
        and r["bucket"] == "all"
    )
    expected = f"{top * 100:.1f}%" if top * 100 < 10 else f"{top * 100:.0f}%"
    assert specs["card_share_top"]["title"] == (
        "No single problem dominates. The biggest holds "
        f"{expected} of all complaints."
    )
    assert specs["bars"]["title"] == "These problems drew the most distinct people on HN."
    assert specs["cost"]["title"] == (
        "The atlas cost $0.26 of Jev credit over 260 calls."
    )
    assert specs["quality"]["title"] == (
        "Jev fit 81% of audited cards; a random card fit 12%."
    )


def test_share_placeholders_use_one_decimal_under_ten(world, tmp_path):
    cmp_json = tmp_path / "cmp-screen.json"
    cmp_json.write_text(json.dumps(ROBUST_SCREEN))
    out = _build(world, tmp_path, robust_screen=str(cmp_json))
    from atlas.sitedata.xspecs import site_chart_specs

    specs = {s["name"]: s for s in site_chart_specs(out)}
    assert specs["wording_range"]["title"] == (
        "Rewording moves the headline between 4.2% and 12%."
    )


def test_run_labels_replace_run_ids_in_bar_labels(world, tmp_path):
    cmp_json = tmp_path / "cmp-screen.json"
    cmp_json.write_text(json.dumps(ROBUST_SCREEN))
    out = _build(world, tmp_path, robust_screen=str(cmp_json))
    from atlas.sitedata.xspecs import site_chart_specs

    specs = {s["name"]: s for s in site_chart_specs(out)}
    labels = [r["label"] for r in specs["wording_range"]["data"]["rows"]]
    assert "original wording (main)" in labels
    assert "rewording 1 (paraphrase)" in labels
    assert not any("screen-syn" in x or "screen-para" in x for x in labels)
    meta = {r["key"]: r["value"] for r in read(out, "meta")}
    assert json.loads(meta["run_labels"]) == {
        "screen-syn": "original wording",
        "screen-para": "rewording 1",
    }


def test_unknown_placeholder_is_an_error(world, tmp_path):
    out = _build(
        world,
        tmp_path,
        toml='[titles]\ncost = "It cost {totl_usd}."\n',
    )
    from atlas.sitedata.xspecs import site_chart_specs

    with pytest.raises(ValueError, match="totl_usd"):
        site_chart_specs(out)


def test_missing_placeholder_data_keeps_generated_title(tmp_path):
    # Fixture tables carry no assignment audit, so the real config's
    # {jev_precision}/{random_precision} template falls back.
    from atlas.sitedata.fixtures import write_fixtures
    from atlas.sitedata.xspecs import site_chart_specs

    write_fixtures(tmp_path / "site", seed=0)
    spec_q = {s["name"]: s for s in site_chart_specs(tmp_path / "site")}[
        "quality"
    ]
    assert spec_q["title"] == (
        "The human audit compares Jev's card precision with a "
        "random-card baseline."
    )


def test_fill_title_formats_and_errors():
    from atlas.sitedata.xspecs import fill_title

    values = {
        "top_share": 0.042,
        "min_share": 0.116,
        "total_usd": 0.26,
        "total_calls": 260,
        "jev_precision": 0.81,
        "random_precision": 0.12,
    }
    assert fill_title("{top_share} x", values) == "4.2% x"
    assert fill_title("{min_share} x", values) == "12% x"
    assert fill_title("{total_usd} / {total_calls}", values) == "$0.26 / 260"
    assert fill_title("{total_calls}", {"total_calls": 312345}) == "312,345"
    assert fill_title("{top_share}", {"top_share": 0.5}) == "50%"
    assert fill_title("{top_share}", {}) is None
    with pytest.raises(ValueError, match="bogus"):
        fill_title("{bogus}", values)


def test_long_title_shrinks_and_stays_on_canvas(tmp_path):
    from atlas.sitedata.xcharts import TITLE_PX, render_x_chart

    title = (
        "These need cards drew the most distinct authors across the whole "
        "sampled window and the pattern held in every segment Jev looked at."
    )
    rec = render_x_chart({**spec("bars"), "title": title}, tmp_path / "t.png")
    assert png_size(tmp_path / "t.png") == (1600, 900)
    assert rec["title_lines"] <= 2
    assert rec["title_bbox"][2] <= 1600 - 24
    assert TITLE_PX * 0.69 <= rec["title_px"] < TITLE_PX


def test_short_title_stays_one_line_at_full_size(tmp_path):
    from atlas.sitedata.xcharts import TITLE_PX, render_x_chart

    rec = render_x_chart(spec("bars"), tmp_path / "t.png")
    assert rec["title_lines"] == 1
    assert rec["title_px"] == pytest.approx(TITLE_PX)
    assert rec["title_bbox"][2] <= 1600 - 24


def test_very_long_title_never_overflows(tmp_path):
    from atlas.sitedata.xcharts import render_x_chart

    title = "A perfectly reasonable sentence that just keeps going " * 8
    title = title.strip() + "."
    rec = render_x_chart({**spec("bars"), "title": title}, tmp_path / "t.png")
    assert rec["title_bbox"][2] <= 1600 - 24
    assert rec["title_bbox"][0] >= 0

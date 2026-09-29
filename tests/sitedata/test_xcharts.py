"""X-ready PNG charts: 1600x900, caveats drawn inside the image."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from tests.sitedata.world import build, build_world

CAVEATS = ("as classified by Jev", "HN comments only; not market demand")
COMMON = {
    "source": "Hacker News comments (official API)",
    "window": "2025-09-28 to 2026-09-28",
    "n": 12345,
    "denominator": "48,000 sampled comments Jev screened as firsthand",
    "lane": "breadth",
    "run_id": "screen-syn",
}
ROWS = [
    {"label": "c01: Synthetic need one", "value": 40, "ci_low": 30, "ci_high": 52},
    {"label": "c02: Synthetic need two", "value": 25, "ci_low": 18, "ci_high": 33},
    {"label": "c03: Synthetic need three", "value": 12},
]
SPECS = {
    "bars": {
        "title": "Three synthetic needs lead by distinct authors.",
        "data": {"rows": ROWS, "xlabel": "distinct authors"},
    },
    "heat": {
        "title": "Synthetic needs spread across several domains.",
        "data": {
            "rows": ["c01", "c02"],
            "cols": ["infra", "data", "dev"],
            "values": [[5, 3, 0], [1, 7, 2]],
            "label": "comments",
        },
    },
    "change": {
        "title": "No synthetic need changed much between half-years.",
        "data": {
            "rows": [
                {"label": "c01", "estimate": 0.02, "ci_low": -0.01, "ci_high": 0.05},
                {"label": "c02", "estimate": -0.03, "ci_low": -0.07, "ci_high": 0.0},
            ],
            "xlabel": "change in share, H2 minus H1",
        },
    },
    "cost": {
        "title": "The synthetic analysis cost four cents of Jev credit.",
        "data": {
            "calculated_usd": 0.04,
            "calls": 260,
            "p50_ms": 510.0,
            "wall_s": 900.0,
        },
    },
    "quality": {
        "title": "Jev beat the random-card baseline on the synthetic audit.",
        "data": {
            "rows": [
                {
                    "label": "Jev card assignment (audit)",
                    "value": 0.81,
                    "ci_low": 0.72,
                    "ci_high": 0.88,
                },
                {
                    "label": "Random card (baseline)",
                    "value": 0.12,
                    "ci_low": 0.03,
                    "ci_high": 0.25,
                },
                {"label": "Firsthand screen accuracy", "value": 0.9, "synthetic": True},
            ]
        },
    },
}


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR"
    return struct.unpack(">II", head[16:24])


def spec(kind: str) -> dict:
    return {"kind": kind, **COMMON, **SPECS[kind]}


@pytest.mark.parametrize("kind", sorted(SPECS))
def test_chart_is_1600x900_with_footer_inside(kind, tmp_path):
    from atlas.sitedata.xcharts import render_x_chart

    out = tmp_path / f"{kind}.png"
    rec = render_x_chart(spec(kind), out)
    assert png_size(out) == (1600, 900)
    footer = rec["footer"]
    for part in (
        COMMON["source"],
        COMMON["window"],
        "12,345",
        COMMON["denominator"],
        COMMON["lane"],
        COMMON["run_id"],
        *CAVEATS,
    ):
        assert part in footer, part
    assert rec["footer_px"] >= 32
    x0, y0, x1, y1 = rec["footer_bbox"]
    assert 0 <= x0 < x1 <= 1600 and 0 <= y0 < y1 <= 900
    assert rec["title"] == SPECS[kind]["title"]
    sidecar = json.loads(out.with_suffix(".json").read_text())
    assert sidecar["footer"] == footer and sidecar["kind"] == kind


def test_synthetic_rows_are_labeled_synthetic_cases(tmp_path):
    from atlas.sitedata.xcharts import render_x_chart

    rec = render_x_chart(spec("quality"), tmp_path / "q.png")
    labels = [r["label"] for r in rec["data"]["rows"]]
    assert labels[2] == "Firsthand screen accuracy (synthetic cases)"
    assert all("synthetic" not in x for x in labels[:2])


@pytest.mark.parametrize(
    "title", ["top cards", "Top cards by authors", "the top cards grew."]
)
def test_title_must_be_a_full_sentence(title, tmp_path):
    from atlas.sitedata.xcharts import render_x_chart

    with pytest.raises(ValueError, match="sentence"):
        render_x_chart({**spec("bars"), "title": title}, tmp_path / "b.png")


@pytest.mark.parametrize(
    "key", ["source", "window", "n", "denominator", "lane", "run_id"]
)
def test_footer_fields_are_required(key, tmp_path):
    from atlas.sitedata.xcharts import render_x_chart

    bad = spec("bars")
    del bad[key]
    with pytest.raises(ValueError, match=key):
        render_x_chart(bad, tmp_path / "b.png")


def test_charts_from_built_site_data(tmp_path, monkeypatch):
    from atlas.sitedata.xcharts import render_site_charts, site_chart_specs

    build_world(tmp_path / "repo", monkeypatch)
    data = tmp_path / "site-real"
    build(data)
    specs = site_chart_specs(data)
    assert [s["kind"] for s in specs] == ["bars", "heat", "change", "cost", "quality"]
    for s in specs:
        assert s["title"].endswith(".") and s["title"][0].isupper()
        assert s["window"] == "2025-09-28 to 2026-09-28"
    quality = next(s for s in specs if s["kind"] == "quality")
    labels = [r["label"] for r in quality["data"]["rows"]]
    assert any("Random card" in x for x in labels)
    assert any(x.endswith("(synthetic cases)") for x in labels)
    cost = next(s for s in specs if s["kind"] == "cost")["data"]
    assert cost["calls"] == 120 + 80 + 40 + 20
    written = render_site_charts(data, tmp_path / "x")
    assert len(written) == 5
    for p in written:
        assert png_size(p) == (1600, 900)


def test_x_charts_cli_writes_pngs(tmp_path, monkeypatch, capsys):
    from atlas import cli as atlas_cli

    build_world(tmp_path / "repo", monkeypatch)
    data = tmp_path / "site-real"
    build(data)
    out = tmp_path / "x" / "2026-09-29"
    args = atlas_cli.build_parser().parse_args(
        ["x", "charts", "--data", str(data), "--out", str(out)])
    args.func(args)
    pngs = sorted(out.glob("*.png"))
    assert [p.name for p in pngs] == ["01-bars.png", "02-heat.png", "03-change.png",
                                     "04-cost.png", "05-quality.png"]
    assert all(png_size(p) == (1600, 900) for p in pngs)
    assert len(capsys.readouterr().out.strip().splitlines()) == 5

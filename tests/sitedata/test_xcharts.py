"""X-ready PNG charts: 1600x900, caveats drawn inside the image."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from tests.sitedata.world import build, build_world, read

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


NAMES = [
    "bars",
    "heat",
    "group_share",
    "card_share_top",
    "card_change",
    "wording_range",
    "cost",
    "quality",
]


def test_charts_from_built_site_data(tmp_path, monkeypatch):
    from atlas.sitedata.xcharts import render_site_charts, site_chart_specs

    build_world(tmp_path / "repo", monkeypatch)
    data = tmp_path / "site-real"
    build(data)
    specs = site_chart_specs(data)
    assert [s["name"] for s in specs] == NAMES
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
    assert len(written) == len(NAMES)
    for p in written:
        assert png_size(p) == (1600, 900)


def test_share_and_change_specs_come_from_card_share(tmp_path, monkeypatch):
    build_world(tmp_path / "repo", monkeypatch)
    data = tmp_path / "site-real"
    screen_json = tmp_path / "cmp-screen.json"
    screen_json.write_text(
        json.dumps(
            {
                "main_run": "screen-syn",
                "sample_id": "sub",
                "cutoff": 0.7,
                "n_sample": 8,
                "runs": {
                    "screen-syn": {
                        "n": 8,
                        "prevalence": 0.5,
                        "ci_low": 0.3,
                        "ci_high": 0.7,
                    },
                    "screen-para": {
                        "n": 8,
                        "prevalence": 0.45,
                        "ci_low": 0.25,
                        "ci_high": 0.65,
                        "vs_main": {
                            "n": 8,
                            "agreement": 0.9,
                            "kappa": 0.7,
                            "spearman": 0.8,
                        },
                    },
                },
            }
        )
    )
    build(data, robust_screen=str(screen_json))
    from atlas.sitedata.xcharts import site_chart_specs

    specs = {s["name"]: s for s in site_chart_specs(data)}
    n_fh = sum(
        1
        for r in read(data, "evidence")
        if r["account_type"] == "firsthand_account"
    )
    card = {
        (r["level"], r["id"], r["bucket"]): r
        for r in read(data, "card_share")
        if r["population"] == "screen_positive"
    }
    for name in ("group_share", "card_share_top", "card_change"):
        spec = specs[name]
        assert spec["qualifier"] == "as classified by Jev; assignment audited"
        assert f"{n_fh:,}" in spec["denominator"]
    groups = specs["group_share"]["data"]["rows"]
    assert [r["label"] for r in groups] == [
        card[("group", g, "all")]["label"]
        for g in sorted(
            ("g01", "g02"),
            key=lambda g: -card[("group", g, "all")]["share"],
        )
    ]
    for r in groups:
        x = card[("group", r["id"], "all")]
        assert r["value"] == x["share"]
        assert r["ci_low"] == x["lo"] and r["ci_high"] == x["hi"]
    top = specs["card_share_top"]["data"]["rows"]
    assert len(top) <= 12
    diff = specs["card_change"]["data"]["rows"]
    for r in diff:
        x = card[("card", r["id"], "H2_minus_H1")]
        assert r["estimate"] == x["share"] * 100
        assert r["significant"] == (x["p_adj"] is not None and x["p_adj"] < 0.05)


def test_wording_range_spec_from_fixture_tables(tmp_path):
    from atlas.sitedata.fixtures import write_fixtures
    from atlas.sitedata.xcharts import render_x_chart, site_chart_specs

    write_fixtures(tmp_path / "site", seed=0)
    specs = {s["name"]: s for s in site_chart_specs(tmp_path / "site")}
    spec = specs["wording_range"]
    rows = spec["data"]["rows"]
    labels = [r["label"] for r in rows]
    assert any("main" in x for x in labels)
    assert any("para" in x for x in labels)
    assert all(r["ci_low"] <= r["value"] <= r["ci_high"] for r in rows)
    for name, s in specs.items():
        rec = render_x_chart(s, tmp_path / "x" / f"{name}.png")
        assert png_size(tmp_path / "x" / f"{name}.png") == (1600, 900)
        for part in (
            s["source"],
            s["window"],
            s["denominator"],
            s["lane"],
            s["run_id"],
            *CAVEATS,
        ):
            assert part in rec["footer"], (name, part)


def _change_dir(tmp_path, diffs):
    """Minimal site dir: meta + a card_share table with crafted diffs."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    d = tmp_path / "site"
    d.mkdir(parents=True)
    pq.write_table(
        pa.table({"key": ["source"], "value": ["synthetic"]}),
        d / "meta.parquet",
    )
    rows = []
    for cid, share, p_adj in diffs:
        for bucket in ("all", "H1", "H2"):
            rows.append(
                {
                    "level": "card",
                    "id": cid,
                    "label": f"Card {cid}",
                    "short_label": f"Card {cid}",
                    "population": "screen_positive",
                    "bucket": bucket,
                    "share": 0.05,
                    "lo": 0.04,
                    "hi": 0.06,
                    "n_items": 3,
                    "n_authors": 2,
                    "p_adj": None,
                    "qualifier": "q",
                }
            )
        rows.append(
            {
                "level": "card",
                "id": cid,
                "label": f"Card {cid}",
                "short_label": f"Card {cid}",
                "population": "screen_positive",
                "bucket": "H2_minus_H1",
                "share": share,
                "lo": share - 0.02,
                "hi": share + 0.02,
                "n_items": 3,
                "n_authors": 2,
                "p_adj": p_adj,
                "qualifier": "q",
            }
        )
    pq.write_table(pa.Table.from_pylist(rows), d / "card_share.parquet")
    return d


def test_card_change_selects_significant_movers(tmp_path):
    from atlas.sitedata.xspecs import site_chart_specs

    diffs = [
        ("c01", 0.050, 0.01),
        ("c02", 0.030, 0.02),
        ("c03", -0.020, 0.03),
        ("c04", -0.040, 0.04),
        # Bigger moves that did not clear p < 0.05 stay off the chart.
        ("c05", -0.200, 0.90),
        ("c06", 0.150, 0.80),
    ]
    spec_c = {s["name"]: s for s in site_chart_specs(_change_dir(tmp_path, diffs))}[
        "card_change"
    ]
    rows = spec_c["data"]["rows"]
    assert [r["id"] for r in rows] == ["c01", "c02", "c03", "c04"]
    assert all(r["significant"] for r in rows)


def test_card_change_fills_with_largest_moves(tmp_path):
    from atlas.sitedata.xspecs import site_chart_specs

    diffs = [
        ("c01", 0.050, 0.01),
        ("c02", -0.040, 0.03),
        ("c03", -0.200, 0.90),
        ("c04", 0.150, 0.80),
        ("c05", 0.010, 0.70),
    ]
    rows = {
        s["name"]: s for s in site_chart_specs(_change_dir(tmp_path, diffs))
    }["card_change"]["data"]["rows"]
    assert [r["id"] for r in rows] == ["c04", "c01", "c02", "c03"]
    assert [r["significant"] for r in rows] == [False, True, True, False]


def test_card_change_caps_eight_risers_and_fallers(tmp_path):
    from atlas.sitedata.xspecs import site_chart_specs

    diffs = [
        *[(f"r{i:02d}", 0.20 - i * 0.01, 0.01) for i in range(10)],
        *[(f"f{i:02d}", -0.20 + i * 0.01, 0.01) for i in range(10)],
    ]
    rows = {
        s["name"]: s for s in site_chart_specs(_change_dir(tmp_path, diffs))
    }["card_change"]["data"]["rows"]
    risers = [r for r in rows if r["estimate"] > 0]
    fallers = [r for r in rows if r["estimate"] < 0]
    assert len(risers) == 8 and len(fallers) == 8
    assert {r["id"] for r in risers} == {f"r{i:02d}" for i in range(8)}
    assert {r["id"] for r in fallers} == {f"f{i:02d}" for i in range(8)}


def test_bar_value_labels_use_one_decimal_under_ten():
    from atlas.sitedata.xcharts import _fmt

    assert _fmt(0.042, "pct") == "4.2%"
    assert _fmt(0.095, "pct") == "9.5%"
    assert _fmt(0.116, "pct") == "12%"
    assert _fmt(0.5, "pct") == "50%"
    assert _fmt(0.0, "pct") == "0.0%"


def test_adjacent_row_labels_never_intersect(tmp_path):
    from itertools import pairwise

    from atlas.sitedata.xcharts import render_x_chart

    bars = {
        **spec("bars"),
        "data": {
            "rows": [
                {
                    "label": f"A fairly long synthetic need statement {i} "
                    "that wraps onto a second line",
                    "value": 30 - i,
                }
                for i in range(6)
            ],
            "xlabel": "distinct authors",
        },
    }
    change = {
        **spec("change"),
        "data": {
            "rows": [
                {
                    "label": f"Another long synthetic need statement {i} "
                    "spanning several wrapped label lines",
                    "estimate": float(4 - i),
                    "ci_low": float(4 - i) - 1,
                    "ci_high": float(4 - i) + 1,
                    "significant": i % 2 == 0,
                }
                for i in range(6)
            ],
            "xlabel": "change",
        },
    }
    for name, s in (("bars", bars), ("change", change)):
        rec = render_x_chart(s, tmp_path / f"{name}.png")
        boxes = sorted(rec["row_label_boxes"], key=lambda b: b[1])
        assert len(boxes) == 6, (name, boxes)
        for a, b in pairwise(boxes):
            assert a[3] <= b[1] + 1.5, (name, a, b)


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
    assert [p.name for p in pngs] == [
        f"{i + 1:02d}-{name}.png" for i, name in enumerate(NAMES)
    ]
    assert all(png_size(p) == (1600, 900) for p in pngs)
    assert len(capsys.readouterr().out.strip().splitlines()) == len(NAMES)

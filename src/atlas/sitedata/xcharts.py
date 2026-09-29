"""X-ready PNG charts (1600x900) whose caveats are drawn inside the image.

``render_x_chart(spec, out_png)`` draws one chart and records what it drew:
the footer string (source, window, n and denominator, lane, run ID, "as
classified by Jev", and "HN comments only; not market demand"), its pixel
size (never below 32 px), and its bounding box. The record is returned and
written next to the PNG as JSON, so a test or a reviewer can check the footer
without OCR. A screenshot of the chart can never lose the caveats.
"""

from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

from atlas.sitedata.xcharts_kinds import _bars, _change, _cost, _heat
from atlas.sitedata.xcharts_layout import (
    ACCENT,
    DPI,
    INK,
    LIGHT,
    MARGIN,
    MUTED,
    TICK_PX,
    TITLE_PX,
    H,
    W,
    _empty,
    _fit_tick_font,
    _fit_title,
    _fmt,
    _labels_clear,
    _pt,
    _row_axis,
    _rule,
    _style,
    _tick_boxes,
    _two_lines,
)

__all__ = [
    "ACCENT",
    "CAVEATS",
    "DPI",
    "FOOTER_FIELDS",
    "FOOTER_PX",
    "INK",
    "KINDS",
    "LIGHT",
    "MARGIN",
    "MUTED",
    "SYNTHETIC",
    "TICK_PX",
    "TITLE_PX",
    "H",
    "W",
    "_bars",
    "_change",
    "_cost",
    "_empty",
    "_fit_tick_font",
    "_fit_title",
    "_fmt",
    "_heat",
    "_labels_clear",
    "_pt",
    "_row_axis",
    "_rule",
    "_style",
    "_tick_boxes",
    "_two_lines",
    "footer_text",
    "render_site_charts",
    "render_x_chart",
    "site_chart_specs",
]

FOOTER_PX = 32
KINDS = ("bars", "heat", "change", "cost", "quality")
FOOTER_FIELDS = ("source", "window", "n", "denominator", "lane", "run_id")
CAVEATS = ("as classified by Jev", "HN comments only; not market demand")
SYNTHETIC = "synthetic cases"


def _check(spec: dict) -> None:
    if spec.get("kind") not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {spec.get('kind')!r}")
    for key in FOOTER_FIELDS:
        if spec.get(key) in (None, ""):
            raise ValueError(f"spec needs {key!r} for the footer")
    title = str(spec.get("title") or "").strip()
    if not (title[:1].isupper() and title[-1:] in ".!?" and len(title.split()) >= 4):
        raise ValueError(f"title must be a full sentence: {title!r}")


def _n_text(n) -> str:
    return f"{n:,}" if isinstance(n, int | float) and not isinstance(n, bool) else str(n)


def footer_text(spec: dict) -> str:
    return " · ".join(_footer_parts(spec, _n_text(spec["n"])))


def _footer_parts(spec: dict, n_txt) -> list[str]:
    return [
        f"Source: {spec['source']}",
        f"Window: {spec['window']}",
        f"n = {n_txt} of {spec['denominator']}",
        f"Lane: {spec['lane']}",
        f"Run: {spec['run_id']}",
        spec.get("qualifier") or CAVEATS[0],
        CAVEATS[1],
    ]


def _pack(parts: list[str], width: int) -> str:
    """Greedy lines of whole footer parts; a part is split only if it alone
    is wider than a line."""
    lines: list[str] = []
    for part in parts:
        for piece in textwrap.wrap(part, width) or [part]:
            if lines and len(lines[-1]) + 3 + len(piece) <= width:
                lines[-1] += " · " + piece
            else:
                lines.append(piece)
    return "\n".join(lines)


def _normalize(spec: dict) -> dict:
    spec = copy.deepcopy(spec)
    if spec["kind"] == "quality":
        for row in spec["data"].get("rows", []):
            if row.get("synthetic") and SYNTHETIC not in row["label"]:
                row["label"] = f"{row['label']} ({SYNTHETIC})"
    return spec


def render_x_chart(spec: dict, out_png) -> dict:
    """Draw one chart to ``out_png`` (1600x900) and return what was drawn."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    _check(spec)
    spec = _normalize(spec)
    footer = footer_text(spec)
    fig = Figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor="white")
    canvas = FigureCanvasAgg(fig)
    renderer = canvas.get_renderer()
    title_txt, title_pt = _fit_title(fig, renderer, spec["title"])
    title = fig.text(
        MARGIN / W,
        1 - MARGIN / H,
        title_txt,
        fontsize=title_pt,
        weight="bold",
        va="top",
        color=INK,
    )
    parts = _footer_parts(spec, _n_text(spec["n"]))
    for width in range(96, 20, -4):
        text = fig.text(
            MARGIN / W,
            0.6 * MARGIN / H,
            _pack(parts, width),
            fontsize=_pt(FOOTER_PX),
            va="bottom",
            color=INK,
            linespacing=1.25,
        )
        box = text.get_window_extent(renderer)
        if box.x1 <= W - MARGIN / 2:
            break
        text.remove()
    tb = title.get_window_extent(renderer)
    fig.add_artist(_rule(fig, (box.y1 + 14) / H))
    # Room below the axes for tick labels and the axis label; room above the
    # heat strip for its column labels.
    below = 40 if spec["kind"] in ("heat", "cost") else 110
    above = 100 if spec["kind"] == "heat" else 28
    bottom, top = (box.y1 + below) / H, (tb.y0 - above) / H
    left = 0.05 if spec["kind"] == "cost" else 0.30
    area = (left, bottom, 0.95 - left, top - bottom)
    ax = None
    if spec["kind"] == "cost":
        _cost(fig, (0.05, bottom, 0.9, top - bottom), spec["data"])
    else:
        ax = fig.add_axes(area)
        if spec["kind"] == "heat":
            _heat(ax, renderer, spec["data"])
        elif spec["kind"] == "change":
            _change(ax, renderer, spec["data"])
        else:
            _bars(
                ax,
                renderer,
                spec["data"],
                "pct"
                if spec["kind"] == "quality"
                else spec["data"].get("format", "int"),
            )
    row_boxes = (
        [
            [round(v, 1) for v in t.get_window_extent(renderer).extents]
            for t in ax.get_yticklabels()
            if t.get_text().strip()
        ]
        if ax is not None
        else []
    )
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=DPI, facecolor="white")
    record = {
        **spec,
        "footer": footer,
        "footer_px": FOOTER_PX,
        "title_px": round(title_pt * DPI / 72, 1),
        "title_lines": title_txt.count("\n") + 1,
        "title_bbox": [round(v, 1) for v in tb.extents],
        "footer_bbox": [
            round(box.x0, 1),
            round(box.y0, 1),
            round(box.x1, 1),
            round(box.y1, 1),
        ],
        "row_label_boxes": row_boxes,
        "width": W,
        "height": H,
    }
    out_png.with_suffix(".json").write_text(
        json.dumps(record, indent=1, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return record


def render_site_charts(site_dir, out_dir) -> list[Path]:
    """Render every chart spec built from a site data directory."""
    from atlas.sitedata.xspecs import site_chart_specs

    out_dir = Path(out_dir)
    written = []
    for i, spec in enumerate(site_chart_specs(site_dir), start=1):
        path = out_dir / f"{i:02d}-{spec.get('name') or spec['kind']}.png"
        render_x_chart(spec, path)
        written.append(path)
    return written


def site_chart_specs(site_dir) -> list[dict]:
    from atlas.sitedata.xspecs import site_chart_specs as build

    return build(site_dir)

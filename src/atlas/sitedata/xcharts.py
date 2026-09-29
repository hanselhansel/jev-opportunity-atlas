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

W, H, DPI = 1600, 900, 100
MARGIN = 48
FOOTER_PX = 32
TITLE_PX = 46
TICK_PX = 22
KINDS = ("bars", "heat", "change", "cost", "quality")
FOOTER_FIELDS = ("source", "window", "n", "denominator", "lane", "run_id")
CAVEATS = ("as classified by Jev", "HN comments only; not market demand")
SYNTHETIC = "synthetic cases"
INK, MUTED, ACCENT, LIGHT = "#1f2328", "#57606a", "#2f6fb0", "#9cc3e6"


def _pt(px: float) -> float:
    return px * 72 / DPI


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


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=_pt(TICK_PX), colors=INK)


def _two_lines(text: str) -> str:
    """Split into two lines at the word boundary closest to the middle."""
    words = text.split()
    if len(words) < 2:
        return text
    k = min(
        range(1, len(words)),
        key=lambda k: abs(
            len(" ".join(words[:k])) - len(" ".join(words[k:]))
        ),
    )
    return " ".join(words[:k]) + "\n" + " ".join(words[k:])


def _fit_title(fig, renderer, raw: str) -> tuple[str, float]:
    """A title that fits the canvas, and its point size.

    One line at full size first, then a balanced two-line wrap, shrinking
    in 10% steps to 70%. Past that the font keeps shrinking to 40%, and as
    a last resort the title wraps to as many lines as it needs — nothing
    ever overflows the 1600 px canvas.
    """
    max_w = W - 2 * MARGIN
    probe = fig.text(0, 0, raw, fontsize=_pt(TITLE_PX), weight="bold")
    try:
        for scale in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
            size = _pt(TITLE_PX) * scale
            probe.set_fontsize(size)
            probe.set_text(raw)
            if probe.get_window_extent(renderer).width <= max_w:
                return raw, size
            two = _two_lines(raw)
            if two != raw:
                probe.set_text(two)
                if probe.get_window_extent(renderer).width <= max_w:
                    return two, size
        size = _pt(TITLE_PX) * 0.4
        probe.set_fontsize(size)
        lo, hi_w, best = 10, len(raw), None
        while lo <= hi_w:
            mid = (lo + hi_w) // 2
            probe.set_text(textwrap.fill(raw, mid))
            if probe.get_window_extent(renderer).width <= max_w:
                best, lo = probe.get_text(), mid + 1
            else:
                hi_w = mid - 1
        return best or textwrap.fill(raw, 10), size
    finally:
        probe.remove()


def _fmt(value, fmt: str) -> str:
    if value is None:
        return "n/a"
    if fmt == "pct":
        return f"{value * 100:.0f}%"
    if fmt == "int":
        return f"{round(value):,}"
    return f"{value:.2f}"


def _empty(ax) -> None:
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        "No data in this run.",
        ha="center",
        va="center",
        fontsize=_pt(30),
        color=MUTED,
        transform=ax.transAxes,
    )


def _bars(ax, data: dict, fmt: str = "int") -> None:
    rows = list(data.get("rows", []))[::-1]
    if not rows:
        return _empty(ax)
    y = range(len(rows))
    vals = [r["value"] or 0 for r in rows]
    colors = [LIGHT if r.get("synthetic") else ACCENT for r in rows]
    hatches = ["//" if r.get("synthetic") else "" for r in rows]
    bars = ax.barh(list(y), vals, color=colors, height=0.6)
    for bar, hatch in zip(bars, hatches, strict=True):
        bar.set_hatch(hatch)
    ends = []
    for i, r in enumerate(rows):
        lo, hi = r.get("ci_low"), r.get("ci_high")
        end = vals[i]
        if lo is not None and hi is not None:
            ax.errorbar(
                vals[i],
                i,
                xerr=[[max(vals[i] - lo, 0)], [max(hi - vals[i], 0)]],
                fmt="none",
                ecolor=INK,
                elinewidth=2.5,
                capsize=8,
            )
            end = max(end, hi)
        ends.append(end)
    top = max(ends) or 1
    for i, end in enumerate(ends):
        ax.text(
            end + top * 0.015,
            i,
            _fmt(vals[i], fmt),
            va="center",
            fontsize=_pt(TICK_PX),
            color=INK,
        )
    ax.set_xlim(0, top * 1.15)
    ax.set_yticks(list(y), [textwrap.fill(r["label"], 34) for r in rows])
    ax.set_xlabel(data.get("xlabel", ""), fontsize=_pt(TICK_PX), color=MUTED)
    if fmt == "pct":
        ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    _style(ax)


def _heat(ax, data: dict) -> None:
    vals = data.get("values") or []
    if not vals or not vals[0]:
        return _empty(ax)
    top = max(max(r) for r in vals) or 1
    ax.imshow(vals, cmap="Blues", aspect="auto", vmin=0, vmax=top)
    for i, row in enumerate(vals):
        for j, v in enumerate(row):
            ax.text(
                j,
                i,
                f"{v:,}",
                ha="center",
                va="center",
                fontsize=_pt(TICK_PX),
                color="white" if v > 0.6 * top else INK,
            )
    ax.set_xticks(
        range(len(data["cols"])),
        [textwrap.fill(c.replace("_", " "), 14) for c in data["cols"]],
    )
    ax.set_yticks(
        range(len(data["rows"])), [textwrap.fill(r, 40) for r in data["rows"]]
    )
    ax.xaxis.tick_top()
    ax.tick_params(length=0, labelsize=_pt(TICK_PX - 2), colors=INK)
    for side in ax.spines.values():
        side.set_visible(False)


def _change(ax, data: dict) -> None:
    rows = list(data.get("rows", []))[::-1]
    if not rows:
        return _empty(ax)
    extent = max(
        1e-9,
        *(
            abs(v)
            for r in rows
            for v in (r.get("ci_low"), r.get("ci_high"), r.get("estimate"))
            if v is not None
        ),
    )
    right = extent * 1.12
    for i, r in enumerate(rows):
        sig = bool(r.get("significant"))
        color = ACCENT if sig else MUTED
        if r.get("ci_low") is not None and r.get("ci_high") is not None:
            ax.hlines(i, r["ci_low"], r["ci_high"], color=color, lw=4 if sig else 3)
        ax.plot(r["estimate"], i, "o", ms=14, color=INK if sig else MUTED)
        ax.text(
            right,
            i,
            f"{r['estimate']:+.1f}" if sig else "no clear change",
            ha="right",
            va="center",
            fontsize=_pt(TICK_PX - 2),
            color=ACCENT if sig else MUTED,
        )
    ax.axvline(0, color=MUTED, ls="--", lw=1.5)
    ax.set_xlim(-extent * 1.08, right + extent * 0.05)
    ax.set_yticks(range(len(rows)), [textwrap.fill(r["label"], 34) for r in rows])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel(data.get("xlabel", ""), fontsize=_pt(TICK_PX), color=MUTED)
    _style(ax)


def _cost(fig, box, data: dict) -> None:
    left, bottom, width, height = box
    wall = data.get("wall_s") or 0.0
    wall_txt = f"{wall / 3600:.1f} h" if wall >= 3600 else f"{wall / 60:.0f} min"
    p50 = data.get("p50_ms")
    tiles = [
        (f"${data.get('calculated_usd') or 0:,.2f}", "calculated USD"),
        (f"{int(data.get('calls') or 0):,}", "Jev calls"),
        ("n/a" if p50 is None else f"{p50:,.0f} ms", "p50 latency"),
        (wall_txt, "wall time"),
    ]
    for i, (value, label) in enumerate(tiles):
        x = left + width * (i + 0.5) / len(tiles)
        y = bottom + height * 0.55
        fig.text(
            x,
            y,
            value,
            ha="center",
            va="bottom",
            fontsize=_pt(76),
            weight="bold",
            color=INK,
        )
        fig.text(
            x, y - 0.02, label, ha="center", va="top", fontsize=_pt(30), color=MUTED
        )


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
    if spec["kind"] == "cost":
        _cost(fig, (0.05, bottom, 0.9, top - bottom), spec["data"])
    else:
        ax = fig.add_axes(area)
        if spec["kind"] == "heat":
            _heat(ax, spec["data"])
        elif spec["kind"] == "change":
            _change(ax, spec["data"])
        else:
            _bars(
                ax,
                spec["data"],
                "pct"
                if spec["kind"] == "quality"
                else spec["data"].get("format", "int"),
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
        "width": W,
        "height": H,
    }
    out_png.with_suffix(".json").write_text(
        json.dumps(record, indent=1, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return record


def _rule(fig, y: float):
    from matplotlib.lines import Line2D

    return Line2D(
        [MARGIN / W, 1 - MARGIN / W],
        [y, y],
        color=MUTED,
        lw=1,
        transform=fig.transFigure,
    )


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

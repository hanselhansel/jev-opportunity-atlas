"""Per-kind drawing for the X charts: bars, heat grid, change dots, and
the cost tiles."""

from __future__ import annotations

import textwrap

from atlas.sitedata.xcharts_layout import (
    ACCENT,
    INK,
    LIGHT,
    MUTED,
    TICK_PX,
    _empty,
    _fit_tick_font,
    _fmt,
    _pt,
    _row_axis,
    _style,
)


def _bars(ax, renderer, data: dict, fmt: str = "int") -> None:
    rows = list(data.get("rows", []))[::-1]
    if not rows:
        return _empty(ax)
    y, lines = _row_axis(ax, renderer, [r["label"] for r in rows])
    vals = [r["value"] or 0 for r in rows]
    colors = [LIGHT if r.get("synthetic") else ACCENT for r in rows]
    hatches = ["//" if r.get("synthetic") else "" for r in rows]
    bars = ax.barh(
        y, vals, color=colors, height=[min(0.8 * n, 1.6) for n in lines]
    )
    for bar, hatch in zip(bars, hatches, strict=True):
        bar.set_hatch(hatch)
    ends = []
    for i, r in enumerate(rows):
        lo, hi = r.get("ci_low"), r.get("ci_high")
        end = vals[i]
        if lo is not None and hi is not None:
            ax.errorbar(
                vals[i],
                y[i],
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
            y[i],
            _fmt(vals[i], fmt),
            va="center",
            fontsize=_pt(TICK_PX),
            color=INK,
        )
    ax.set_xlim(0, top * 1.15)
    ax.set_xlabel(data.get("xlabel", ""), fontsize=_pt(TICK_PX), color=MUTED)
    if fmt == "pct":
        ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    _style(ax)


def _heat(ax, renderer, data: dict) -> None:
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
    _fit_tick_font(ax, renderer, "y")
    _fit_tick_font(ax, renderer, "x")
    for side in ax.spines.values():
        side.set_visible(False)


def _change(ax, renderer, data: dict) -> None:
    rows = list(data.get("rows", []))[::-1]
    if not rows:
        return _empty(ax)
    y, _ = _row_axis(ax, renderer, [r["label"] for r in rows])
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
            ax.hlines(y[i], r["ci_low"], r["ci_high"], color=color, lw=4 if sig else 3)
        ax.plot(r["estimate"], y[i], "o", ms=14, color=INK if sig else MUTED)
        ax.text(
            right,
            y[i],
            f"{r['estimate']:+.1f}" if sig else "no clear change",
            ha="right",
            va="center",
            fontsize=_pt(TICK_PX - 2),
            color=ACCENT if sig else MUTED,
        )
    ax.axvline(0, color=MUTED, ls="--", lw=1.5)
    ax.set_xlim(-extent * 1.08, right + extent * 0.05)
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

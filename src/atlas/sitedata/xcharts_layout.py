"""Canvas constants and layout helpers for the X charts.

Title fitting, wrapped row axes, tick-label spacing, and the shared ink
and spine styling every chart kind draws with.
"""

from __future__ import annotations

import textwrap

W, H, DPI = 1600, 900, 100
MARGIN = 48
TITLE_PX = 46
TICK_PX = 22
INK, MUTED, ACCENT, LIGHT = "#1f2328", "#57606a", "#2f6fb0", "#9cc3e6"


def _pt(px: float) -> float:
    return px * 72 / DPI


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
        if abs(value) * 100 < 10:
            return f"{value * 100:.1f}%"
        return f"{value * 100:.0f}%"
    if fmt == "int":
        return f"{round(value):,}"
    return f"{value:.2f}"


def _labels_clear(boxes, axis="y") -> bool:
    """Adjacent tick-label boxes, sorted bottom-to-top (or left-to-right),
    never intersect."""
    from itertools import pairwise

    if axis == "y":
        boxes = sorted(boxes, key=lambda b: b.y0)
        return all(a.y1 <= b.y0 + 1 for a, b in pairwise(boxes))
    boxes = sorted(boxes, key=lambda b: b.x0)
    return all(a.x1 <= b.x0 + 1 for a, b in pairwise(boxes))


def _tick_boxes(ax, renderer, axis="y") -> list:
    labels = ax.get_yticklabels() if axis == "y" else ax.get_xticklabels()
    return [
        t.get_window_extent(renderer) for t in labels if t.get_text().strip()
    ]


def _row_axis(ax, renderer, labels, wrap=34, gap=0.5):
    """Row centers spaced by each label's wrapped line count; the tick
    font shrinks until adjacent labels clear. Returns (y, line counts)."""
    wrapped = [textwrap.fill(str(l), wrap) for l in labels]
    lines = [w.count("\n") + 1 for w in wrapped]
    y, edge = [], 0.0
    for n in lines:
        y.append(edge + n / 2)
        edge += n + gap
    total = max(edge - gap, 1)
    scale = 1.0
    for _ in range(8):
        ax.set_ylim(0, total)
        ax.set_yticks(y, wrapped)
        ax.tick_params(axis="y", labelsize=_pt(TICK_PX) * scale)
        if _labels_clear(_tick_boxes(ax, renderer)):
            break
        scale *= 0.85
    return y, lines


def _fit_tick_font(ax, renderer, axis="y", base_px=TICK_PX - 2) -> float:
    """Shrink an axis's tick font until adjacent labels clear."""
    scale = 1.0
    for _ in range(8):
        ax.tick_params(axis=axis, labelsize=_pt(base_px) * scale)
        if _labels_clear(_tick_boxes(ax, renderer, axis), axis):
            return scale
        scale *= 0.85
    return scale


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


def _rule(fig, y: float):
    from matplotlib.lines import Line2D

    return Line2D(
        [MARGIN / W, 1 - MARGIN / W],
        [y, y],
        color=MUTED,
        lw=1,
        transform=fig.transFigure,
    )

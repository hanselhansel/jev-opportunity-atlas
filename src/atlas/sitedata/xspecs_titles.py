"""Configured titles for the X charts.

``load_x_titles`` reads ``configs/x_titles.toml``; ``fill_title`` fills the
``{placeholder}`` fields of a configured title with formatted values,
returning None when a value is missing so the caller keeps the generated
title.
"""

from __future__ import annotations

import string
import tomllib

from atlas import paths


def load_x_titles() -> tuple[dict, dict]:
    """``(titles, run_labels)`` from ``configs/x_titles.toml``; both empty
    when the file is absent."""
    path = paths.CONFIGS / "x_titles.toml"
    if not path.exists():
        return {}, {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("titles") or {}), dict(data.get("run_labels") or {})


def _share_fmt(v: float) -> str:
    """One decimal under 10%, a whole percent otherwise."""
    return f"{v * 100:.1f}%" if abs(v) * 100 < 10 else f"{v * 100:.0f}%"


_PLACEHOLDERS = {
    "top_share": _share_fmt,
    "min_share": _share_fmt,
    "max_share": _share_fmt,
    "jev_precision": _share_fmt,
    "random_precision": _share_fmt,
    "total_usd": lambda v: f"${v:,.2f}",
    "total_calls": lambda v: f"{int(v):,}",
}


def fill_title(template: str, values: dict) -> str | None:
    """Fill ``{placeholder}`` fields in a configured title. An unknown
    placeholder is an error; a known one with no data returns None so the
    caller keeps the generated title."""
    fields = {
        name
        for _, name, _, _ in string.Formatter().parse(template)
        if name is not None
    }
    fields.discard("")
    unknown = fields - set(_PLACEHOLDERS)
    if unknown:
        raise ValueError(
            f"unknown x_titles placeholder(s): {sorted(unknown)}"
        )
    if any(values.get(f) is None for f in fields):
        return None
    return template.format(
        **{f: _PLACEHOLDERS[f](values[f]) for f in fields}
    )

"""``story.json`` IO: the Estimate object and atomic per-section writes.

Every published number is an ``Est``: a point estimate, 50% and 95%
bootstrap intervals, the contributing row count ``n``, and ``sparse``
(too few rows to trust). ``merge_section`` is the only writer: lanes add
their own top-level keys to ``story.json`` without touching anyone else's.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

MIN_N = 30  # below this many rows an estimate is flagged ``sparse``


def _f(x) -> float | None:
    return float(x) if x is not None and math.isfinite(float(x)) else None


def est(est, lo50=None, hi50=None, lo95=None, hi95=None, n=0) -> dict | None:
    """One Estimate object; ``None`` when the point estimate is not finite."""
    if _f(est) is None:
        return None
    return {
        "est": _f(est),
        "lo50": _f(lo50),
        "hi50": _f(hi50),
        "lo95": _f(lo95),
        "hi95": _f(hi95),
        "n": int(n),
        "sparse": int(n) < MIN_N,
    }


def merge_section(path, key: str, value) -> None:
    """Set ``doc[key] = value`` in ``story.json``, atomically.

    The document is canonical (sorted keys, fixed indent), so a section written
    by an earlier lane re-serializes byte-identically when a later lane merges.
    """
    path = Path(path)
    doc = {}
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if text.strip():
            doc = json.loads(text)
    doc[key] = value
    blob = (
        json.dumps(
            doc, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(blob, encoding="utf-8")
    os.replace(tmp, path)

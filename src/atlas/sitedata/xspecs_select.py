"""Row selection for the X chart specs.

``select_change_rows`` picks the card rows for the change chart; the other
helpers shape ``card_share`` rows for the share and change specs.
"""

from __future__ import annotations


def _by_share(rows, bucket="all"):
    return sorted(
        (r for r in rows if r["bucket"] == bucket),
        key=lambda r: (-(r["share"] or 0.0), r["id"]),
    )


def _pct(x):
    return None if x is None else x * 100


def _short(r) -> str:
    """Display label for a card_share row: the labels.yaml short_label when
    the build wrote one, else the full card or group text."""
    return r.get("short_label") or r["label"]


def select_change_rows(diff_rows, min_sig=4, per_side=8) -> list[dict]:
    """The card rows for the change chart: those that moved (``p_adj <
    0.05``), up to ``per_side`` risers and fallers each, sorted by change.
    When fewer than ``min_sig`` qualify, the largest absolute changes fill
    in as non-significant rows, drawn muted with "no clear change".
    """
    sig = [
        r
        for r in diff_rows
        if r["share"] is not None
        and r["p_adj"] is not None
        and r["p_adj"] < 0.05
    ]
    risers = sorted(
        (r for r in sig if r["share"] > 0),
        key=lambda r: (-r["share"], r["id"]),
    )[:per_side]
    fallers = sorted(
        (r for r in sig if r["share"] < 0),
        key=lambda r: (r["share"], r["id"]),
    )[:per_side]
    picked = {r["id"]: r for r in risers + fallers}
    if len(picked) < min_sig:
        rest = sorted(
            (
                r
                for r in diff_rows
                if r["share"] is not None and r["id"] not in picked
            ),
            key=lambda r: (-abs(r["share"]), r["id"]),
        )
        for r in rest[: min_sig - len(picked)]:
            picked[r["id"]] = r
    return sorted(
        picked.values(), key=lambda r: (-(r["share"] or 0.0), r["id"])
    )

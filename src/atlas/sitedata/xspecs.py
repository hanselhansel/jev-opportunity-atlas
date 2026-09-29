"""Chart specs for the X exports, built only from a site data directory.

Eight named charts: top cards by distinct authors, a problem x domain heat
strip, group and top-card shares of firsthand problems from ``card_share``, a
half-year change dot plot on the cards that moved (``p_adj < 0.05``, with
the largest moves filling in when few qualify), a
wording-robustness range from ``robustness``, a cost and time panel, and a Jev
quality panel (audit precision against the random-card baseline, and the
synthetic benchmark labeled "synthetic cases"). Titles are full sentences that
describe the chart without asserting a result the data may not show.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from atlas.sitedata.xspecs_panels import (
    _cost_spec,
    _quality_spec,
    _wording_spec,
)
from atlas.sitedata.xspecs_select import (
    _by_share,
    _pct,
    _short,
    select_change_rows,
)
from atlas.sitedata.xspecs_titles import (
    _PLACEHOLDERS,
    _share_fmt,
    fill_title,
    load_x_titles,
)

__all__ = [
    "FIRSTHAND",
    "POPULATION",
    "_PLACEHOLDERS",
    "_by_share",
    "_cost_spec",
    "_pct",
    "_quality_spec",
    "_rows",
    "_share_fmt",
    "_short",
    "_wording_spec",
    "fill_title",
    "load_x_titles",
    "select_change_rows",
    "site_chart_specs",
]

POPULATION = "screen_positive"
FIRSTHAND = "firsthand_account"


def _rows(site_dir: Path, name: str) -> list[dict]:
    path = site_dir / f"{name}.parquet"
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


def site_chart_specs(site_dir, top_n=10, top_cards=12, n_boot=1000, seed=0) -> list[dict]:
    site_dir = Path(site_dir)
    titles, run_labels = load_x_titles()
    meta = {r["key"]: r["value"] for r in _rows(site_dir, "meta")}
    findings = _rows(site_dir, "findings")
    fe = [r for r in _rows(site_dir, "finding_evidence") if r["role"] == "supporting"]
    evidence = _rows(site_dir, "evidence")
    runs = _rows(site_dir, "runs")
    quality = _rows(site_dir, "quality")
    card_share = _rows(site_dir, "card_share")
    robustness = _rows(site_dir, "robustness")
    n_faceted = int(meta.get("n_faceted") or len(evidence))
    n_fh = sum(1 for r in evidence if r["account_type"] == FIRSTHAND)
    common = {
        "source": meta.get("source") or "Hacker News comments",
        "window": f"{meta.get('window_start', '')[:10]} to {meta.get('window_end', '')[:10]}",
        "lane": meta.get("lane") or "breadth",
    }
    denom = f"{n_faceted:,} firsthand problems Jev faceted"
    fh_denom = (
        f"{n_fh:,} firsthand problems Jev classified"
        if n_fh
        else "firsthand problems Jev classified"
    )
    assign_run = meta.get("assign_run") or meta.get("run_id")
    top = sorted(findings, key=lambda f: (-f["n_authors"], f["finding_id"]))[:top_n]
    label = {
        f["finding_id"]: f.get("short_label") or f["title"] for f in top
    }
    members = {
        f["finding_id"]: {
            r["comment_id"] for r in fe if r["finding_id"] == f["finding_id"]
        }
        for f in top
    }
    domain_of = {r["comment_id"]: r["domain"] for r in evidence}

    bars = {
        **common,
        "kind": "bars",
        "name": "bars",
        "run_id": assign_run,
        "denominator": denom,
        "n": sum(len(m) for m in members.values()),
        "title": f"These {len(top)} need cards drew the most distinct authors in the sample.",
        "data": {
            "rows": [
                {
                    "id": f["finding_id"],
                    "label": label[f["finding_id"]],
                    "full_label": f["title"],
                    "value": f["n_authors"],
                }
                for f in top
            ],
            "xlabel": "distinct authors (sample counts)",
            "format": "int",
        },
    }

    counts: dict[str, dict[str, int]] = {}
    for fid, ids in members.items():
        for cid in ids:
            d = domain_of.get(cid)
            if d is not None:
                counts.setdefault(fid, {}).setdefault(d, 0)
                counts[fid][d] += 1
    totals: dict[str, int] = {}
    for per in counts.values():
        for d, v in per.items():
            totals[d] = totals.get(d, 0) + v
    cols = sorted(totals, key=lambda d: (-totals[d], d))[:8]
    heat = {
        **common,
        "kind": "heat",
        "name": "heat",
        "run_id": assign_run,
        "denominator": denom,
        "n": sum(totals.values()),
        "title": "This grid counts comments on each top need card by the domain Jev assigned.",
        "data": {
            "rows": [label[f] for f in members],
            "cols": cols,
            "values": [[counts.get(f, {}).get(d, 0) for d in cols] for f in members],
            "label": "comments",
        },
    }

    shares = [r for r in card_share if r["population"] == POPULATION]
    group_all = _by_share([r for r in shares if r["level"] == "group"])
    card_all = _by_share([r for r in shares if r["level"] == "card"])[:top_cards]
    qualifier = (group_all or card_all or [{}])[0].get("qualifier")
    group_share = {
        **common,
        "kind": "bars",
        "name": "group_share",
        "run_id": assign_run,
        "denominator": fh_denom,
        "n": sum(r["n_items"] or 0 for r in group_all),
        "qualifier": qualifier,
        "title": "Each need group holds this share of all firsthand problems.",
        "data": {
            "rows": [
                {
                    "id": r["id"],
                    "label": _short(r),
                    "full_label": r["label"],
                    "value": r["share"],
                    "ci_low": r["lo"],
                    "ci_high": r["hi"],
                }
                for r in group_all
            ],
            "xlabel": "share of firsthand problems",
            "format": "pct",
        },
    }
    card_share_top = {
        **common,
        "kind": "bars",
        "name": "card_share_top",
        "run_id": assign_run,
        "denominator": fh_denom,
        "n": sum(r["n_items"] or 0 for r in card_all),
        "qualifier": qualifier,
        "title": f"These are the {len(card_all)} largest need cards by share of firsthand problems.",
        "data": {
            "rows": [
                {
                    "id": r["id"],
                    "label": _short(r),
                    "full_label": r["label"],
                    "value": r["share"],
                    "ci_low": r["lo"],
                    "ci_high": r["hi"],
                }
                for r in card_all
            ],
            "xlabel": "share of firsthand problems",
            "format": "pct",
        },
    }

    diff = select_change_rows(
        [
            r
            for r in shares
            if r["level"] == "card" and r["bucket"] == "H2_minus_H1"
        ]
    )
    card_change = {
        **common,
        "kind": "change",
        "name": "card_change",
        "run_id": assign_run,
        "denominator": fh_denom,
        "n": sum(r["n_items"] or 0 for r in diff),
        "qualifier": qualifier,
        "title": "This chart shows how each need card's share moved between half-years.",
        "data": {
            "rows": [
                {
                    "id": r["id"],
                    "label": _short(r),
                    "full_label": r["label"],
                    "estimate": _pct(r["share"]),
                    "ci_low": _pct(r["lo"]),
                    "ci_high": _pct(r["hi"]),
                    "significant": r["p_adj"] is not None and r["p_adj"] < 0.05,
                }
                for r in diff
                if r["share"] is not None
            ],
            "xlabel": "change in share of firsthand problems, H2 minus H1 (points)",
        },
    }

    wording_range, prev = _wording_spec(common, robustness, run_labels)
    cost, usd, calls = _cost_spec(common, runs)
    qual, audit = _quality_spec(common, quality, assign_run)
    specs = [
        bars,
        heat,
        group_share,
        card_share_top,
        card_change,
        wording_range,
        cost,
        qual,
    ]
    shares = [r["value"] for r in prev if r["value"] is not None]
    values = {
        "top_share": card_all[0]["share"] if card_all else None,
        "min_share": min(shares) if shares else None,
        "max_share": max(shares) if shares else None,
        "total_usd": usd if runs else None,
        "total_calls": calls if runs else None,
        "jev_precision": next(
            (r["value"] for r in audit if r["system"] == "jev"), None
        ),
        "random_precision": next(
            (r["value"] for r in audit if r["system"] == "random_card"), None
        ),
    }
    for s in specs:
        template = titles.get(s["name"])
        if template:
            s["title"] = fill_title(template, values) or s["title"]
    return specs

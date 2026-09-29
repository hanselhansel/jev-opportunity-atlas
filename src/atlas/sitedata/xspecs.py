"""Chart specs for the X exports, built only from a site data directory.

Eight named charts: top cards by distinct authors, a problem x domain heat
strip, group and top-card shares of firsthand problems from ``card_share``, a
half-year change dot plot on the top cards (``p_adj < 0.05`` highlighted), a
wording-robustness range from ``robustness``, a cost and time panel, and a Jev
quality panel (audit precision against the random-card baseline, and the
synthetic benchmark labeled "synthetic cases"). Titles are full sentences that
describe the chart without asserting a result the data may not show.
"""

from __future__ import annotations

import string
import tomllib
from pathlib import Path

import pyarrow.parquet as pq

from atlas import paths

POPULATION = "screen_positive"
FIRSTHAND = "firsthand_account"


def _rows(site_dir: Path, name: str) -> list[dict]:
    path = site_dir / f"{name}.parquet"
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


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

    top_ids = {r["id"] for r in card_all}
    diff = _by_share(
        [
            r
            for r in shares
            if r["level"] == "card"
            and r["bucket"] == "H2_minus_H1"
            and r["id"] in top_ids
        ],
        bucket="H2_minus_H1",
    )
    card_change = {
        **common,
        "kind": "change",
        "name": "card_change",
        "run_id": assign_run,
        "denominator": fh_denom,
        "n": sum(r["n_items"] or 0 for r in diff),
        "qualifier": qualifier,
        "title": "This chart shows how each top card's share moved between half-years.",
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

    prev = [
        r
        for r in robustness
        if r["check"] == "screen_wording" and r["metric"] == "prevalence"
    ]
    para_runs = {
        r["run_id"]
        for r in robustness
        if r["metric"] in ("agreement", "kappa", "spearman")
    }
    wording_range = {
        **common,
        "kind": "bars",
        "name": "wording_range",
        "run_id": "+".join(r["run_id"] for r in prev) or "none",
        "denominator": (
            f"{prev[0]['n']:,} comments in the paraphrase subsample"
            if prev and prev[0].get("n")
            else "comments in the paraphrase subsample"
        ),
        "n": prev[0]["n"] if prev else 0,
        "title": "The headline prevalence moves this much when the question is reworded.",
        "data": {
            "rows": [
                {
                    "label": (
                        f"{run_labels.get(r['run_id'], r['run_id'])} (paraphrase)"
                        if r["run_id"] in para_runs
                        else f"{run_labels.get(r['run_id'], r['run_id'])} (main)"
                    ),
                    "value": r["value"],
                    "ci_low": r["lo"],
                    "ci_high": r["hi"],
                }
                for r in prev
            ],
            "xlabel": "prevalence of firsthand problems at the screen cutoff",
            "format": "pct",
        },
    }

    calls = sum(r["calls"] or 0 for r in runs)
    usd = sum(r["calculated_usd"] or 0.0 for r in runs)
    biggest = max(runs, key=lambda r: r["calls"] or 0, default={})
    by_phase: dict[str, dict] = {}
    for r in runs:
        phase = r["phase"] or "unknown"
        b = by_phase.setdefault(
            phase,
            {
                "phase": phase,
                "calculated_usd": 0.0,
                "calls": 0,
                "runs": 0,
                "wall_s": 0.0,
            },
        )
        b["calculated_usd"] += r["calculated_usd"] or 0.0
        b["calls"] += r["calls"] or 0
        b["runs"] += 1
        b["wall_s"] += r["wall_s"] or 0.0
    phases = sorted(
        by_phase.values(), key=lambda b: (-b["calculated_usd"], b["phase"])
    )
    cost = {
        **common,
        "kind": "cost",
        "name": "cost",
        "run_id": (
            f"{len(runs)} runs across {len(phases)} phases" if runs else "none"
        ),
        "denominator": "Jev calls across all runs",
        "n": calls,
        "title": f"The runs behind this atlas cost ${usd:,.2f} of Jev credit over {calls:,} calls.",
        "data": {
            "calculated_usd": usd,
            "calls": calls,
            "p50_ms": biggest.get("p50_ms"),
            "wall_s": sum(r["wall_s"] or 0.0 for r in runs),
            "phases": phases,
        },
    }

    names = {
        "jev": "Jev card assignment (human audit)",
        "random_card": "Random card (baseline)",
    }
    audit = [
        r
        for r in quality
        if r["label_set"] == "assignment_audit"
        and r["metric"] == "precision_strict"
        and r["system"] in names
    ]
    audit.sort(key=lambda r: list(names).index(r["system"]))
    bench = [r for r in quality if r["label_set"] == "synthetic"]
    qrows = [
        {
            "label": names[r["system"]],
            "value": r["value"],
            "ci_low": r["ci_low"],
            "ci_high": r["ci_high"],
        }
        for r in audit
    ]
    qrows += [
        {
            "label": (
                f"{r['question_id'].replace('_', ' ')} "
                f"{r['metric'].replace('_', ' ')} (synthetic cases)"
            ),
            "value": r["value"],
            "synthetic": True,
        }
        for r in bench
    ]
    jev_n = next((r["n"] for r in audit if r["system"] == "jev"), None)
    qual = {
        **common,
        "kind": "quality",
        "name": "quality",
        "run_id": assign_run,
        "denominator": "audited card assignments" if jev_n else "benchmark cases",
        "n": jev_n or sum(r["n"] or 0 for r in bench),
        "title": "The human audit compares Jev's card precision with a random-card baseline.",
        "data": {"rows": qrows, "xlabel": "precision or accuracy"},
    }
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

"""Chart specs for the X exports, built only from a site data directory.

Five charts: top cards by distinct authors, a problem x domain heat strip, a
half-year change dot plot with intervals, a cost and time panel, and a Jev
quality panel (audit precision against the random-card baseline, and the
synthetic benchmark labeled "synthetic cases"). Titles are full sentences
that describe the chart without asserting a result the data may not show.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

H1 = {f"P{i:02d}" for i in range(1, 7)}


def _rows(site_dir: Path, name: str) -> list[dict]:
    return pq.read_table(site_dir / f"{name}.parquet").to_pylist()


def _half_change(evidence, members, n_boot=1000, seed=0, alpha=0.05):
    """Per card: weighted share of evidence in H2 minus H1, in points, with a
    percentile interval from resampling threads within each half."""
    rng = np.random.default_rng(seed)
    est = np.zeros(len(members))
    boot = np.zeros((n_boot, len(members)))
    for sign, half in ((-1.0, True), (1.0, False)):
        rows = [
            r
            for r in evidence
            if r["period"] is not None and (r["period"] in H1) == half
        ]
        if not rows:
            return [None] * len(members), [None] * len(members), [None] * len(members)
        _, inv = np.unique([str(r["story_id"]) for r in rows], return_inverse=True)
        w = np.array([r["weight"] or 1.0 for r in rows])
        ind = np.array(
            [[r["comment_id"] in m for m in members] for r in rows], dtype=float
        )
        sums = np.zeros((inv.max() + 1, 1 + len(members)))
        np.add.at(sums, inv, np.column_stack([w, w[:, None] * ind]))
        tot = sums.sum(axis=0)
        est += sign * tot[1:] / tot[0]
        k = sums.shape[0]
        rep = rng.multinomial(k, np.full(k, 1.0 / k), size=n_boot) @ sums
        with np.errstate(divide="ignore", invalid="ignore"):
            boot += sign * rep[:, 1:] / rep[:, [0]]
    lo, hi = np.nanquantile(boot, [alpha / 2, 1 - alpha / 2], axis=0)
    return list(est * 100), list(lo * 100), list(hi * 100)


def site_chart_specs(site_dir, top_n=10, n_boot=1000, seed=0) -> list[dict]:
    site_dir = Path(site_dir)
    meta = {r["key"]: r["value"] for r in _rows(site_dir, "meta")}
    findings = _rows(site_dir, "findings")
    fe = [r for r in _rows(site_dir, "finding_evidence") if r["role"] == "supporting"]
    evidence = _rows(site_dir, "evidence")
    runs = _rows(site_dir, "runs")
    quality = _rows(site_dir, "quality")
    n_faceted = int(meta.get("n_faceted") or len(evidence))
    common = {
        "source": meta.get("source") or "Hacker News comments",
        "window": f"{meta.get('window_start', '')[:10]} to {meta.get('window_end', '')[:10]}",
        "lane": meta.get("lane") or "breadth",
    }
    denom = f"{n_faceted:,} firsthand problems Jev faceted"
    assign_run = meta.get("assign_run") or meta.get("run_id")
    top = sorted(findings, key=lambda f: (-f["n_authors"], f["finding_id"]))[:top_n]
    label = {f["finding_id"]: f"{f['finding_id']}: {f['title']}" for f in top}
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
        "run_id": assign_run,
        "denominator": denom,
        "n": sum(len(m) for m in members.values()),
        "title": f"These {len(top)} need cards drew the most distinct authors in the sample.",
        "data": {
            "rows": [
                {"label": label[f["finding_id"]], "value": f["n_authors"]} for f in top
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

    est, lo, hi = _half_change(evidence, list(members.values()), n_boot, seed)
    change = {
        **common,
        "kind": "change",
        "run_id": assign_run,
        "denominator": denom,
        "n": len(evidence),
        "title": "This chart shows how each top need card's share moved between half-years.",
        "data": {
            "rows": [
                {"label": label[f], "estimate": e, "ci_low": a, "ci_high": b}
                for f, e, a, b in zip(members, est, lo, hi, strict=True)
                if e is not None
            ],
            "xlabel": "change in share of firsthand problems, H2 minus H1 (points)",
        },
    }

    calls = sum(r["calls"] or 0 for r in runs)
    usd = sum(r["calculated_usd"] or 0.0 for r in runs)
    biggest = max(runs, key=lambda r: r["calls"] or 0, default={})
    cost = {
        **common,
        "kind": "cost",
        "run_id": " + ".join(r["run_id"] for r in runs) or "none",
        "denominator": "Jev calls across all runs",
        "n": calls,
        "title": f"The runs behind this atlas cost ${usd:,.2f} of Jev credit over {calls:,} calls.",
        "data": {
            "calculated_usd": usd,
            "calls": calls,
            "p50_ms": biggest.get("p50_ms"),
            "wall_s": sum(r["wall_s"] or 0.0 for r in runs),
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
        "run_id": assign_run,
        "denominator": "audited card assignments" if jev_n else "benchmark cases",
        "n": jev_n or sum(r["n"] or 0 for r in bench),
        "title": "The human audit compares Jev's card precision with a random-card baseline.",
        "data": {"rows": qrows, "xlabel": "precision or accuracy"},
    }
    return [bars, heat, change, cost, qual]

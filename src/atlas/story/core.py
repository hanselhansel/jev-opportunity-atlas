"""Core story sections: funnel, groups, cards, unplaced, domains, roles.

Every share is a weighted share of firsthand problems (phase-2 ``pos`` rows
whose facets@2 account_type is ``firsthand_account``), computed from one
``boot.Replicates`` object so all buckets and the H2 - H1 change share the
same cluster draws. The neg check slice enters only ``domains.discussion``
and the funnel's per-month firsthand share, which describe every screened
comment. ``unplaced`` keeps the no-card residue visible instead of dropping
it from the denominator.
"""

from __future__ import annotations

import json
import math
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from atlas import paths
from atlas.estimation.robust import bootstrap_pvalue
from atlas.story.boot import Replicates, summarize

TITLE = (
    "Startup opportunities identified via Hacker News conversations "
    "between 2025-26"
)
SCHEMA = "story.v1"
PERIODS = [f"P{i:02d}" for i in range(1, 13)]
QUARTERS = {
    f"Q{i}": [f"P{3 * i - 2:02d}", f"P{3 * i - 1:02d}", f"P{3 * i:02d}"]
    for i in range(1, 5)
}
_H1 = frozenset(PERIODS[:6])
_H2 = frozenset(PERIODS[6:])
BUCKETS = ["all", "h1", "h2", *QUARTERS, *PERIODS]
FUNNEL_LABELS = {
    "all": "All comments in the window",
    "eligible": "Eligible comments",
    "screened": "Screened by Jev",
    "firsthand": "Firsthand problems",
    "placed": "Matched to a need card",
}
UNSTATED_ROLES = {"unclear", "other"}


def _codes(values, cats: list[str]) -> np.ndarray:
    """Integer codes of ``values`` in ``cats``; -1 for anything else."""
    pos_map = {v: k for k, v in enumerate(cats)}
    return np.array([pos_map.get(v, -1) for v in values])


def _mask(period: np.ndarray, bucket: str) -> np.ndarray:
    if bucket == "all":
        return np.ones(period.size, dtype=bool)
    if bucket == "h1":
        return np.isin(period, list(_H1))
    if bucket == "h2":
        return np.isin(period, list(_H2))
    if bucket in QUARTERS:
        return np.isin(period, QUARTERS[bucket])
    return period == bucket


def _bh_adjust(pvalues: np.ndarray) -> np.ndarray:
    """BH step-up adjusted p-values (same convention as the site tables)."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p, kind="stable")
    ranked = p[order] * m / np.arange(1, m + 1)
    adj_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.clip(adj_sorted, 0.0, 1.0)
    return out


def _fin(x) -> float | None:
    return float(x) if x is not None and math.isfinite(x) else None


def _shares(rep: Replicates, frame, key: str, ids: list[str]):
    """Per-id Est per bucket plus the joint H2 - H1 difference replicates."""
    period = frame["period"].astype(object).to_numpy()
    codes = _codes(frame[key], ids)
    match = codes[:, None] == np.arange(len(ids))[None, :]
    j = len(ids)
    reps_r = rep.counts.shape[0]
    ests: dict[str, list] = {}
    half: dict[str, tuple] = {}
    for b in BUCKETS:
        den = _mask(period, b)
        nums = den[:, None] & match
        point, reps = rep.ratio(nums.astype(float), den.astype(float))
        ns = nums.sum(axis=0).astype(int)
        ests[b] = [
            summarize(point[k], reps[:, k], int(ns[k])) for k in range(j)
        ]
        if b in ("h1", "h2"):
            half[b] = (point, reps)
    p1, r1 = half.get("h1", (np.full(j, np.nan), np.full((reps_r, j), np.nan)))
    p2, r2 = half.get("h2", (np.full(j, np.nan), np.full((reps_r, j), np.nan)))
    diff_reps = r2 - r1
    diff_est = np.where(np.isfinite(p1) & np.isfinite(p2), p2 - p1, np.nan)
    return ests, diff_est, diff_reps


def _change_block(diff_est, diff_reps, shrink: bool):
    """Change dicts per id; ``p_adj`` is BH-adjusted within this family."""
    j = len(diff_est)
    pvals = np.array(
        [
            bootstrap_pvalue(diff_reps[:, k])
            if np.isfinite(diff_est[k])
            else np.nan
            for k in range(j)
        ]
    )
    adj = np.full(j, np.nan)
    ok = np.isfinite(pvals)
    if ok.any():
        adj[ok] = _bh_adjust(pvals[ok])
    out = []
    shrunk = None
    if shrink:
        se = np.nanstd(diff_reps, axis=0)
        finite = np.isfinite(diff_est) & np.isfinite(se)
        tau2 = 0.0
        if finite.sum() >= 2:
            tau2 = max(
                0.0,
                float(np.var(diff_est[finite]) - np.mean(se[finite] ** 2)),
            )
        shrunk = np.where(
            finite & (tau2 + se**2 > 0),
            diff_est * tau2 / (tau2 + se**2),
            np.nan,
        )
    for k in range(j):
        if not np.isfinite(diff_est[k]):
            out.append({"est": None, "lo95": None, "hi95": None, "p_adj": None})
            continue
        lo, hi = np.nanquantile(diff_reps[:, k], [0.025, 0.975])
        row = {
            "est": _fin(diff_est[k]),
            "lo95": _fin(lo),
            "hi95": _fin(hi),
            "p_adj": _fin(adj[k]),
        }
        if shrink:
            row["shrunk"] = _fin(shrunk[k])
        out.append(row)
    return out


def _entities(frame, rep, key: str, ids: list[str], shrink: bool):
    """Share Ests for ``all``/``h1``/``h2``/quarters/months plus change."""
    ests, diff_est, diff_reps = _shares(rep, frame, key, ids)
    change = _change_block(diff_est, diff_reps, shrink)
    rows = []
    for k, x in enumerate(ids):
        rows.append(
            {
                "id": x,
                "share": ests["all"][k],
                "h1": ests["h1"][k],
                "h2": ests["h2"][k],
                "change": change[k],
                "quarters": {q: ests[q][k] for q in QUARTERS},
                "months": {p: ests[p][k] for p in PERIODS},
            }
        )
    return rows


def _top_thread_share(fh, group_id: str) -> float:
    sub = fh[fh["group"] == group_id]
    if not len(sub):
        return 0.0
    w = sub["weight"].to_numpy(dtype=float)
    threads = sub["story_id"].to_numpy()
    per_thread = {}
    for t, wv in zip(threads, w):
        per_thread[t] = per_thread.get(t, 0.0) + wv
    return max(per_thread.values()) / w.sum() if w.sum() else 0.0


def _groups_cards(fh, rep_fh, cs, short):
    groups = _entities(fh, rep_fh, "group", sorted(cs.groups), shrink=False)
    cards = _entities(fh, rep_fh, "card", sorted(cs.all_cards), shrink=True)
    card_key = fh["card"].astype(object)
    for row in groups:
        gid = row["id"]
        row.update(
            {
                "label": cs.groups[gid],
                "short": short["groups"].get(gid) or cs.groups[gid],
                "cards": sorted(c for c in cs.all_cards
                                if cs.all_cards[c].group_id == gid),
                "top_thread_share": _top_thread_share(fh, gid),
            }
        )
    for row in cards:
        cid = row["id"]
        sub = fh[card_key == cid]
        row.update(
            {
                "group": cs.all_cards[cid].group_id,
                "short": (
                    short["cards"].get(cid) or cs.all_cards[cid].statement
                ),
                "statement": cs.all_cards[cid].statement,
                "n_problems": len(sub),
                "n_authors": int(sub["author"].dropna().nunique()),
                "n_threads": int(sub["story_id"].nunique()),
            }
        )
        del row["months"]
    return groups, cards


def _unplaced(fh, rep_fh):
    unplaced = fh["card"].isna().to_numpy()
    point, reps = rep_fh.ratio(unplaced.astype(float), np.ones(len(fh)))
    out = {
        "share": summarize(point[0], reps[:, 0], int(unplaced.sum())),
        "domains": {},
        "roles": {},
    }
    for col, bucket in (("domain", "domains"), ("user_role", "roles")):
        vals = sorted(
            {v for v in fh.loc[fh["card"].isna(), col] if isinstance(v, str)}
        )
        if not vals:
            continue
        codes = _codes(fh[col], vals)
        match = codes[:, None] == np.arange(len(vals))[None, :]
        den = unplaced.astype(float)
        nums = unplaced[:, None] & match
        point, reps = rep_fh.ratio(nums.astype(float), den)
        ns = nums.sum(axis=0).astype(int)
        for k, v in enumerate(vals):
            out[bucket][v] = summarize(point[k], reps[:, k], int(ns[k]))
    return out


def _roles(fh, rep_fh, group_ids):
    rolev = fh["user_role"].astype(object).to_numpy()
    stated = np.array(
        [isinstance(r, str) and r not in UNSTATED_ROLES for r in rolev]
    )
    roles = sorted({r for r, s in zip(rolev, stated) if s})
    rcodes = _codes(rolev, roles)
    rmatch = rcodes[:, None] == np.arange(len(roles))[None, :]
    groupv = fh["group"].astype(object).to_numpy()
    by_group, known = {}, {}
    for g in group_ids:
        gm = groupv == g
        den = (gm & stated).astype(float)
        nums = gm[:, None] & rmatch
        point, reps = rep_fh.ratio(nums, den)
        ns = nums.sum(axis=0).astype(int)
        by_group[g] = {
            r: summarize(point[k], reps[:, k], int(ns[k]))
            for k, r in enumerate(roles)
        }
        pk, rk = rep_fh.ratio((gm & stated).astype(float), gm.astype(float))
        known[g] = summarize(pk[0], rk[:, 0], int((gm & stated).sum()))
    return {"by_group": by_group, "known_share": known}


def _period_counts(snapshot_id) -> dict[str, int]:
    cov = paths.snapshot_dir(snapshot_id) / "coverage.parquet"
    out = {}
    if cov.exists():
        for r in pq.read_table(cov).to_pylist():
            if r["dimension"] == "period":
                out[r["key"]] = int(r["count"])
    return out


def _funnel(frame, snapshot_id, screen_run, rep_all):
    snap = paths.snapshot_dir(snapshot_id)
    counts = {}
    mpath = snap / "manifest.json"
    if mpath.exists():
        counts = (json.loads(mpath.read_text()) or {}).get("counts") or {}
    screened = None
    if screen_run:
        p = paths.run_dir(screen_run) / "screen_by_comment.parquet"
        if p.exists():
            screened = pq.read_metadata(p).num_rows
    fhpos = (frame["phase"] == "pos") & frame["firsthand"]
    placed = fhpos & frame["card"].notna()
    w = frame["weight"].to_numpy(dtype=float)

    def _count(mask) -> int:
        return round(float(w[mask.to_numpy()].sum()))

    steps = [
        {"key": k, "label": FUNNEL_LABELS[k], "count": v}
        for k, v in (
            ("all", counts.get("comments")),
            ("eligible", counts.get("eligible")),
            ("screened", screened),
            ("firsthand", _count(fhpos)),
            ("placed", _count(placed)),
        )
    ]
    period = frame["period"].astype(object).to_numpy()
    cov = _period_counts(snapshot_id)
    months = []
    for p in PERIODS:
        den = (period == p).astype(float)
        num = den * fhpos.to_numpy(dtype=float)
        est_v, reps_v = rep_all.ratio(num, den)
        months.append(
            {
                "period": p,
                "comments": cov.get(p, 0),
                "firsthand": summarize(
                    est_v[0], reps_v[:, 0], int(num.sum())
                ),
            }
        )
    return {"steps": steps, "months": months}


def load_story_labels(toml_path=None) -> dict:
    """The ``labels`` section: human labels for the facets@2 domain and
    user_role choice keys, from ``configs/story_labels.toml``."""
    path = (
        Path(toml_path)
        if toml_path
        else paths.CONFIGS / "story_labels.toml"
    )
    if not path.exists():
        return {"domains": {}, "roles": {}}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return {
        "domains": dict(data.get("domains") or {}),
        "roles": dict(data.get("roles") or {}),
    }


def build_core(frame, snapshot_id, screen_run=None, R: int = 1000, seed: int = 0):
    """The S1 sections of ``story.json`` (everything except ``meta`` and
    ``method``, which the CLI writes around this call)."""
    cs = frame.attrs.get("cardset")
    if cs is None:
        from atlas.sitedata.inputs import find_cardset

        cs = find_cardset("t3", "main")
    from atlas.sitedata.build import load_short_labels
    from atlas.story.core_domains import build_domains

    short = load_short_labels(f"{cs.name}.{cs.version}")
    fh = frame[(frame["phase"] == "pos") & frame["firsthand"]]
    rep_fh = Replicates(fh, R=R, seed=seed)
    rep_all = Replicates(frame, R=R, seed=seed)
    groups, cards = _groups_cards(fh, rep_fh, cs, short)
    return {
        "funnel": _funnel(frame, snapshot_id, screen_run, rep_all),
        "groups": groups,
        "cards": cards,
        "unplaced": _unplaced(fh, rep_fh),
        "domains": build_domains(frame, rep_all),
        "roles": _roles(fh, rep_fh, sorted(cs.groups)),
        "labels": load_story_labels(),
    }


def build_meta(snapshot_id, runs: dict, version: str, built_at=None) -> dict:
    """The ``meta`` section: schema, fixed title, window, provenance."""
    from atlas.sitedata.inputs import _code_commit

    snap = paths.snapshot_dir(snapshot_id)
    window = {}
    mpath = snap / "manifest.json"
    if mpath.exists():
        window = (json.loads(mpath.read_text()) or {}).get("window") or {}
    return {
        "schema": SCHEMA,
        "title": TITLE,
        "window_start": window.get("start"),
        "window_end": window.get("end"),
        "built_at": built_at
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "code_commit": _code_commit(),
        "runs": {
            k: runs.get(k)
            for k in (
                "screen", "facets", "assign", "replies", "solutions", "builders"
            )
        },
        "taxonomy": version,
    }

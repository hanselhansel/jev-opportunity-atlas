"""Pooled, time-balanced allocation for the main breadth sample.

A comment's chance of being a firsthand problem should not depend on whether
it was written in H1 or H2, and the pilot's per-half estimates came from ~20
comments each, so pilot firsthand rates and per-comment screen costs are
pooled across the two half-years. The yield allocation runs on the pooled
strata, then each pooled allocation is split across H1 and H2 in proportion
to N so both halves keep the same sampling rate — unlike allocating the
unsplit strata, where greedy fill would overdraw whichever half sorts first.

Ported from the main run's draw script (see docs/runbook-main-run.md).
"""

from __future__ import annotations

import json
from collections import defaultdict


def pooled_key(stratum: str) -> str:
    """Drop the half-year: "pain|L2|H1|ask" -> "pain|L2|ask"."""
    pain, lbin, _half, tg = stratum.split("|")
    return f"{pain}|{lbin}|{tg}"


def _coarse(key: str, obs: dict, min_n: int) -> tuple[float, str]:
    """Borrow from pain|lbin, then pain, then all, when a pooled cell is thin."""
    pain, lbin, _tg = key.split("|")
    for lvl in (key, f"{pain}|{lbin}|", f"{pain}|", ""):
        vals = (
            [v for k, vs in obs.items() if k.startswith(lvl) for v in vs]
            if lvl != key
            else obs.get(key, [])
        )
        if len(vals) >= min_n:
            return sum(vals) / len(vals), lvl or "all"
    vals = [v for vs in obs.values() for v in vs]
    return sum(vals) / len(vals), "all"


def pilot_observations(
    pilot_run: str,
    cutoff: float,
    sample_id: str | None = None,
    question_set: str = "screen@1",
    question_id: str = "firsthand_problem",
) -> tuple[dict, dict]:
    """Pooled pilot observations: firsthand flags and input tokens.

    Returns (obs_p, obs_c) keyed by pooled stratum. obs_p values are booleans
    (`noul >= cutoff`); obs_c values are the ledger's calculated input tokens
    per comment. Both keep the reference semantics: one value per comment,
    last write wins.
    """
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    from atlas import paths
    from atlas.inference.ledger import read_rows

    if sample_id is None:
        pilot_json = paths.run_dir(pilot_run) / "pilot.json"
        if pilot_json.exists():
            sample_id = json.loads(pilot_json.read_text())["sample_id"]
        else:
            sample_id = pilot_run
    pilot = pq.read_table(
        paths.sample_path(sample_id), columns=["comment_id", "stratum"]
    ).to_pylist()
    st_of = {r["comment_id"]: r["stratum"] for r in pilot}

    firsthand: dict = {}
    parts = sorted(
        (paths.run_dir(pilot_run) / "answers").glob("part-*.parquet")
    )
    if parts:
        answers = pq.read_table(
            parts,
            columns=["comment_id", "question_set", "question_id", "noul"],
        )
        answers = answers.filter(
            pc.and_(
                pc.equal(answers.column("question_set"), question_set),
                pc.equal(answers.column("question_id"), question_id),
            )
        )
        for cid, noul in zip(
            answers.column("comment_id").to_pylist(),
            answers.column("noul").to_pylist(),
        ):
            if cid is not None:
                firsthand[cid] = noul

    tokens: dict = {}
    for row in read_rows(paths.ledger_path(pilot_run)):
        if (
            row.get("question_set") == question_set
            and row.get("cost_class") == "calculated"
            and row.get("input_tokens")
        ):
            tokens[row["comment_id"]] = row["input_tokens"]

    obs_p: dict[str, list] = defaultdict(list)
    obs_c: dict[str, list] = defaultdict(list)
    for cid, st in st_of.items():
        if cid in firsthand:
            obs_p[pooled_key(st)].append(firsthand[cid] >= cutoff)
        if cid in tokens:
            obs_c[pooled_key(st)].append(tokens[cid])
    return dict(obs_p), dict(obs_c)


def pooled_allocation(
    N: dict[str, int],
    pilot_obs_p: dict,
    pilot_obs_c: dict,
    budget_tokens: float,
    floor_rate: float,
    cost_scale: float,
    min_pilot_n: int = 20,
    min_n: int = 30,
) -> dict:
    """Yield allocation pooled across half-years, then split back by N.

    `N` is the v2 stratum -> eligible count map; `pilot_obs_p`/`pilot_obs_c`
    are pooled stratum -> observation lists from `pilot_observations`. Returns
    the per-stratum `alloc` plus the inputs downstream manifests record:
    `p` (pooled firsthand rate), `c` (pooled mean tokens times `cost_scale`),
    `levels` (which coarse level backed each estimate), and the pooled
    `alloc_pooled`/`N_pooled` intermediates.
    """
    from atlas.sampling import yield_alloc

    p, c, levels = {}, {}, {}
    for h in N:
        ph, lp = _coarse(pooled_key(h), pilot_obs_p, min_pilot_n)
        ch, lc = _coarse(pooled_key(h), pilot_obs_c, min_pilot_n)
        p[h], c[h] = ph, ch * cost_scale
        levels[h] = {"p": lp, "c": lc}

    n_pooled: dict[str, int] = defaultdict(int)
    members: dict[str, list] = defaultdict(list)
    for h, n_h in N.items():
        n_pooled[pooled_key(h)] += n_h
        members[pooled_key(h)].append(h)
    p_pooled = {k: p[members[k][0]] for k in n_pooled}
    c_pooled = {
        k: sum(c[h] * N[h] for h in members[k]) / n_pooled[k] for k in n_pooled
    }
    alloc_pooled = yield_alloc.allocate_by_yield(
        dict(n_pooled), p_pooled, c_pooled, budget_tokens, floor_rate, min_n
    )
    alloc = {}
    for k, a_k in alloc_pooled.items():
        rate = a_k / n_pooled[k]
        for h in members[k]:
            alloc[h] = min(N[h], max(min(N[h], min_n), round(rate * N[h])))
    return {
        "alloc": alloc,
        "p": p,
        "c": c,
        "levels": levels,
        "alloc_pooled": dict(alloc_pooled),
        "N_pooled": dict(n_pooled),
    }


def draw_pooled(
    *,
    snapshot_id: str,
    pilot_run: str,
    budget_usd: float,
    cost_scale: float,
    cutoff: float,
    seed: int,
    sample_id: str,
    floor_rate: float,
    min_n: int = 30,
    min_pilot_n: int = 20,
) -> dict:
    """Draw the pooled-allocated main sample and write sample + manifest.

    Idempotent: an existing sample id is reused only when every draw parameter
    matches its sidecar; any other existing file raises instead of
    overwriting.
    """
    import hashlib

    import pyarrow.parquet as pq

    from atlas import paths
    from atlas.sampling import design_v2, yield_alloc

    out_path = paths.sample_path(sample_id)
    sidecar_path = paths.SAMPLES / f"{sample_id}.json"
    if out_path.exists():
        if not sidecar_path.exists():
            raise ValueError(
                f"{out_path} exists without a sidecar; refusing to reuse"
            )
        meta = json.loads(sidecar_path.read_text(encoding="utf-8"))
        same = (
            meta.get("sha256")
            == hashlib.sha256(out_path.read_bytes()).hexdigest()
            and meta.get("seed") == seed
            and meta.get("frame_snapshot_id") == snapshot_id
            and meta.get("pilot_run") == pilot_run
            and meta.get("budget_usd") == budget_usd
            and meta.get("cost_scale") == cost_scale
            and meta.get("cutoff") == cutoff
        )
        if not same:
            raise ValueError(
                f"{out_path} exists with different draw parameters"
            )
        design = meta["design"]
        return {
            "sample_id": sample_id,
            "rows": pq.read_table(out_path).num_rows,
            "reused": True,
            "alloc": design["allocation"],
            "expected_positives": design["expected_positives"],
            "expected_tokens": design["expected_tokens"],
            "largest_weight": design["largest_weight"],
            "budget_tokens": design["budget_tokens"],
        }

    sdir = paths.snapshot_dir(snapshot_id)
    comments = pq.read_table(
        sdir / "comments.parquet",
        columns=[
            "id",
            "story_id",
            "period",
            "thread_type",
            "text_norm",
            "word_count",
            "eligible",
        ],
    )
    stories = pq.read_table(
        sdir / "stories.parquet", columns=["id", "thread_type"]
    )
    frame = design_v2.build_frame_v2(comments, stories)
    N: dict[str, int] = {}
    for h in frame.column("stratum").to_pylist():
        N[h] = N.get(h, 0) + 1

    obs_p, obs_c = pilot_observations(pilot_run, cutoff)
    budget_tokens = yield_alloc.usd_to_tokens(budget_usd)
    res = pooled_allocation(
        N,
        obs_p,
        obs_c,
        budget_tokens,
        floor_rate,
        cost_scale,
        min_pilot_n=min_pilot_n,
        min_n=min_n,
    )
    alloc = res["alloc"]
    table = design_v2.draw_allocated(frame, alloc, seed, sample_id)
    design = design_v2.design_block(
        floor_rate=floor_rate,
        min_n=min_n,
        budget_tokens=budget_tokens,
        p=res["p"],
        c=res["c"],
        source=(
            f"pilot:{pilot_run}; p_h at firsthand_problem >= {cutoff}; "
            f"pooled across half-years; c_h x {cost_scale} (packed/single)"
        ),
        alloc=alloc,
        N=N,
        input_levels=res["levels"],
    )
    meta = {
        "sample_id": sample_id,
        "seed": seed,
        "seeds_by_batch": {"1": seed},
        "frame_snapshot_id": snapshot_id,
        "algorithm": (
            "stratified SRSWOR per v2 design stratum; yield allocation with "
            f"{floor_rate * 100:g}% floor; PCG64"
        ),
        "purpose": "main breadth sample",
        "cost_scale": cost_scale,
        "budget_usd": budget_usd,
        "pilot_run": pilot_run,
        "cutoff": cutoff,
    }
    design_v2.write_design_manifest(table, meta, design, paths.SAMPLES)
    return {
        "sample_id": sample_id,
        "rows": table.num_rows,
        "reused": False,
        "alloc": alloc,
        "expected_positives": design["expected_positives"],
        "expected_tokens": design["expected_tokens"],
        "largest_weight": design["largest_weight"],
        "budget_tokens": budget_tokens,
    }

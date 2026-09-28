"""Pilot report: one markdown document over the three pilot run dirs.

Pure local reads. A stage with no run directory is reported as "not run".
Numbers and ids only, never comment text.
"""

from __future__ import annotations

import json
import tomllib
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas import paths
from atlas.inference import ledger as ledger_mod
from atlas.pilot import stages

DISCLAIMER = "calculated from reported usage; not provider-reconciled"
CALIBRATION_NOTE = "calibration only; not a reported quality number"
EVIDENCE = ("workaround", "cost_time", "cost_money", "cost_reliability", "cost_customers")


def _f(value, digits=3):
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "n/a"


def _runs(run_id):
    return (run_id, f"{run_id}-packed", f"{run_id}-injected")


def _manifest(rid):
    path = paths.run_dir(rid) / "run_manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _rows(rid):
    return ledger_mod.read_rows(paths.ledger_path(rid))


def _answers_table(rid):
    parts = sorted((paths.run_dir(rid) / "answers").glob("part-*.parquet"))
    return pq.read_table(parts) if parts else None


def _sec_run(run_id, pilot) -> list[str]:
    lines = [
        f"- `{rid}`{'' if paths.run_dir(rid).is_dir() else ' (not run)'}"
        for rid in _runs(run_id)
    ]
    lines += [
        f"- sample_id: `{pilot['sample_id']}`",
        f"- snapshot_id: `{pilot['snapshot_id']}`",
        f"- model: `{_manifest(run_id).get('model')}`",
    ]
    for rid in _runs(run_id):
        for e in _manifest(rid).get("question_sets", []):
            lines.append(f"- `{rid}` `{e['label']}` sha256 `{e['file_sha256']}`")
    pairs = [
        (r["started_at"], r["ended_at"]) for rid in _runs(run_id)
        for r in _rows(rid) if r.get("started_at") and r.get("ended_at")
    ]
    if pairs:
        lines.append(f"- window: {min(p[0] for p in pairs)} .. {max(p[1] for p in pairs)}")
    return lines


def _sec_cost(run_id) -> list[str]:
    lines, total = [], 0.0
    spec = [
        ("screen", run_id, ("screen@1",)),
        ("facets", run_id, ("facets@1",)),
        ("packed", f"{run_id}-packed", None),
        ("injected", f"{run_id}-injected", None),
    ]
    for name, rid, labels in spec:
        lpath = paths.ledger_path(rid)
        if not lpath.exists():
            lines.append(f"- {name} (`{rid}`): not run")
            continue
        sets = ledger_mod.summarize(lpath, by="question_set").get("question_sets") or {}
        keys = sorted(k for k in sets if labels is None or k in labels)
        usd = sum(sets[k]["calculated_usd"] for k in keys)
        calls = sum(sets[k]["calls"] for k in keys)
        unk = sum(sets[k]["unknown_attempts"] for k in keys)
        total += usd
        lines.append(
            f"- {name} (`{rid}`; {', '.join(keys) or 'none'}): ${usd:.4f} "
            f"over {calls} calls, {unk} unknown attempts ({DISCLAIMER})"
        )
    lines.append(f"- total: ${total:.4f} ({DISCLAIMER})")
    head = stages.budget_headroom("pilot")
    lines.append(
        f"- pilot budget: ${head['committed_usd']:.4f} committed of "
        f"${head['cap_usd']:.4f} cap; ${head['remaining_usd']:.4f} remaining "
        f"({DISCLAIMER})"
    )
    if head["account_total"] is not None:
        lines.append(
            f"- account: ${head['account_committed_usd']:.4f} committed of "
            f"${head['account_total']:.4f}; ${head['account_remaining_usd']:.4f} "
            f"remaining ({DISCLAIMER})"
        )
    return lines


def _token_stats(label, tokens) -> str:
    a = np.asarray(tokens, dtype=float)
    return (
        f"- {label}: n={a.size} mean={a.mean():.0f} "
        f"p50={np.percentile(a, 50):.0f} p95={np.percentile(a, 95):.0f}"
    )


def _sec_tokens(run_id, stratum_of) -> list[str]:
    by_qs: dict[str, list[dict]] = defaultdict(list)
    for rid in _runs(run_id):
        for r in _rows(rid):
            ok = r.get("cost_class") == "calculated" and r.get("question_set")
            if ok and r.get("input_tokens") is not None:
                by_qs[r["question_set"]].append(r)
    lines = [
        _token_stats(qs, [r["input_tokens"] for r in by_qs[qs]])
        for qs in sorted(by_qs)
    ]
    per_stratum: dict[str, list[float]] = defaultdict(list)
    for r in by_qs.get("screen@1", []):
        if (h := stratum_of.get(r.get("comment_id"))) is not None:
            per_stratum[h].append(r["input_tokens"])
    return lines + [
        _token_stats(f"{h} (screen@1)", per_stratum[h])
        for h in sorted(per_stratum)
    ]


def _design(run_id, pilot) -> dict | None:
    """V2 frame + pilot_inputs for the run (the same inputs
    `sample allocate-v2` reads); None when the pilot has no usable data."""
    from atlas.sampling import design_v2, yield_alloc

    sdir = paths.snapshot_dir(pilot["snapshot_id"])
    cols = ["id", "story_id", "period", "thread_type", "text_norm", "word_count", "eligible"]
    comments = pq.read_table(sdir / "comments.parquet", columns=cols)
    stories = pq.read_table(sdir / "stories.parquet", columns=["id", "thread_type"])
    frame = design_v2.build_frame_v2(comments, stories)
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(labels, return_counts=True)
    cfg = tomllib.loads((paths.CONFIGS / "sampling_v2.toml").read_text())
    try:
        p, c, levels = yield_alloc.pilot_inputs(frame, run_id, cfg)
    except ValueError:
        return None
    sizes = {str(u): int(n) for u, n in zip(uniq, counts)}
    return {"sizes": sizes, "cfg": cfg, "p": p, "c": c, "levels": levels}


def _sec_firsthand(run_id, stratum_of, design) -> list[str]:
    if design is None:
        return ["- no usable screen answers or ledger tokens in this run"]
    from atlas.evaluation.queue import read_answers

    answers = read_answers(run_id, "firsthand_problem")
    thr = design["cfg"]["firsthand_threshold"]
    lines = []
    for h in sorted(set(stratum_of.values())):
        ids = [c for c, s in stratum_of.items() if s == h]
        n_scr = sum(answers.get(c, {}).get("noul") is not None for c in ids)
        n_yes = sum((answers.get(c, {}).get("noul") or -1) >= thr for c in ids)
        rate = f"{n_yes / n_scr:.3f}" if n_scr else "n/a"
        level = design["levels"][h]
        lines.append(
            f"- {h}: {n_scr}/{len(ids)} screened, {n_yes} firsthand, raw rate "
            f"{rate}; p_h={design['p'][h]:.3f} (from {level['p']}), "
            f"c_h={design['c'][h]:.0f} tokens (from {level['c']})"
        )
    return lines


def _sec_latency(run_id) -> list[str]:
    lines = []
    for rid in _runs(run_id):
        rows = _rows(rid)
        timed = [r["request_ms"] for r in rows if r.get("request_ms") is not None]
        if not timed:
            lines.append(f"- `{rid}`: not run")
            continue
        a = np.asarray(timed, dtype=float)
        stamps = [
            (datetime.fromisoformat(r["started_at"]), datetime.fromisoformat(r["ended_at"]))
            for r in rows if r.get("started_at") and r.get("ended_at")
        ]
        wall = (max(e for _, e in stamps) - min(s for s, _ in stamps))
        lines.append(
            f"- `{rid}`: p50={np.percentile(a, 50):.0f} ms "
            f"p95={np.percentile(a, 95):.0f} ms wall={wall.total_seconds():.1f} s"
        )
    return lines


def _sec_distributions(run_id) -> list[str]:
    table = _answers_table(run_id)
    if table is None:
        return ["- not run"]
    groups = defaultdict(lambda: defaultdict(list))
    for r in table.to_pylist():
        g = groups[(r["question_set"], r["question_id"])]
        for key in ("noul", "choice", "score"):
            if r[key] is not None:
                g[key].append(r[key])
    lines = []
    for (qs, qid), g in sorted(groups.items()):
        if g["noul"]:
            hist = np.histogram(g["noul"], bins=10, range=(0.0, 1.0))[0].tolist()
            lines.append(f"- {qs} {qid}: noul n={len(g['noul'])} hist={hist}")
        if g["choice"]:
            body = " ".join(f"{k}={v}" for k, v in sorted(Counter(g["choice"]).items()))
            lines.append(f"- {qs} {qid}: choice {body}")
        if g["score"]:
            lines.append(f"- {qs} {qid}: score mean={np.mean(g['score']):.3f} n={len(g['score'])}")
    return lines


def _sec_gate(run_id) -> list[str]:
    from atlas.evaluation.queue import read_answers

    answers = read_answers(run_id, "firsthand_problem")
    nouls = [a["noul"] for a in answers.values() if a["noul"] is not None]
    if not nouls:
        return ["- not run"]
    shares = ", ".join(
        f">= {t}: {sum(v >= t for v in nouls) / len(nouls):.3f}"
        for t in (0.3, 0.5, 0.7)
    )
    lines = [f"- screen@1 firsthand noul share {shares} (n={len(nouls)})"]
    sel_path = paths.run_dir(run_id) / "facet_selection.parquet"
    if not sel_path.exists():
        return lines + ["- facet selection: not run"]
    random_rows = [
        r for r in pq.read_table(sel_path).to_pylist() if r["rule"] == "random"
    ]
    lines.append(
        "- problem evidence in facets@1 = max(workaround, cost_time, "
        "cost_money, cost_reliability, cost_customers noul) >= 0.5"
    )
    if not random_rows:
        return lines + ["- below-gate random comments: 0"]
    ids = {r["comment_id"] for r in random_rows}
    maxima: dict[int, float] = {}
    table = _answers_table(run_id)
    if table is not None:
        sub = table.filter(pc.equal(table.column("question_set"), "facets@1"))
        sub = sub.filter(pc.is_in(sub.column("question_id"), value_set=pa.array(EVIDENCE)))
        id_set = pa.array(sorted(ids), type=pa.int64())
        sub = sub.filter(pc.is_in(sub.column("comment_id"), value_set=id_set))
        for r in sub.to_pylist():
            if r["noul"] is not None:
                cid = r["comment_id"]
                maxima[cid] = max(maxima.get(cid, 0.0), r["noul"])
    n_ev = sum(maxima.get(r["comment_id"], 0.0) >= 0.5 for r in random_rows)
    prob = random_rows[0]["selection_prob"]
    lines.append(
        f"- below-gate random comments: {len(random_rows)}; with problem "
        f"evidence: {n_ev}; weighted estimate the gate would drop in the "
        f"pilot sample: {_f(n_ev / prob if prob else None, 1)} "
        "(= n_evidence / selection_prob)"
    )
    return lines


def _sec_packed(run_id) -> list[str]:
    from atlas.pilot import packed

    packed_id = f"{run_id}-packed"
    pmap_path = paths.run_dir(packed_id) / "packed_map.parquet"
    if not pmap_path.exists():
        return ["- not run"]
    pmap = pq.read_table(pmap_path)
    res = packed.compare_packed(
        _answers_table(run_id),
        packed.unpack_answers(_answers_table(packed_id), pmap),
        single_ledger=paths.ledger_path(run_id),
        packed_ledger=paths.ledger_path(packed_id),
        packed_map=pmap,
    )
    t = res["tokens_per_comment"]
    return [
        (
            f"- n={res['n']} pearson={_f(res['pearson'])} "
            f"agreement@0.5={_f(res['agreement_at_0_5'])} "
            f"mean_abs_diff={_f(res['mean_abs_diff'])}"
        ),
        (f"- tokens/comment single={_f(t['single'], 1)} packed={_f(t['packed'], 1)}"),
    ]


def _sec_injected(run_id) -> list[str]:
    from atlas.pilot import injected

    table = _answers_table(f"{run_id}-injected")
    if table is None:
        return ["- not run"]
    res = injected.injected_accuracy(table, injected.load_cases())
    o = res["overall"]
    return [
        (
            f"- overall: {o['correct']}/{o['n']} correct "
            f"(accuracy {_f(o['accuracy'])}, {o['missing']} missing)"
        ),
        *[
            f"- {t}: {s['correct']}/{s['n']} correct ({_f(s['accuracy'])})"
            for t, s in sorted(res["by_type"].items())
        ],
    ]


def _sec_projection(design) -> list[str]:
    if design is None:
        return ["- pilot inputs unavailable; allocation not possible"]
    from atlas.sampling import yield_alloc

    usd_per_token, _version = yield_alloc.price_per_token()
    cfg = design["cfg"]
    lines = []
    for b in (5.00, 6.50, 8.00):
        try:
            alloc = yield_alloc.allocate_by_yield(
                design["sizes"], design["p"], design["c"], yield_alloc.usd_to_tokens(b),
                cfg["floor_rate"], cfg["min_n"])
        except ValueError as exc:
            lines.append(f"- ${b:.2f}: infeasible: {exc}")
            continue
        cost = yield_alloc.expected_tokens(alloc, design["c"]) * usd_per_token
        lines.append(
            f"- ${b:.2f}: n={sum(alloc.values())}, expected firsthand "
            f"{yield_alloc.expected_positives(alloc, design['p']):.1f}, "
            f"largest weight "
            f"{yield_alloc.largest_weight(alloc, design['sizes']):.0f}, "
            f"expected cost ${cost:.4f}"
        )
    return lines


def _sec_calibration(run_id) -> list[str]:
    path = paths.run_dir(run_id) / "eval_calibration.json"
    if not path.exists():
        return ["- not available"]
    rep = json.loads(path.read_text(encoding="utf-8"))
    thr = rep.get("threshold")
    thr = thr.get("threshold") if isinstance(thr, dict) else thr
    met = (rep.get("stop_rule") or {}).get("met")
    return [
        f"- {CALIBRATION_NOTE}",
        (f"- n_labeled={rep.get('n_labeled')} n_yes={rep.get('n_yes')} "
         f"n_no={rep.get('n_no')}"),
        f"- threshold={_f(thr, 2)} stop_rule_met={met}",
    ]


def build_report(run_id) -> str:
    """Markdown report over the pilot's three run directories."""
    pilot = stages.read_pilot_json(run_id)
    sample = pq.read_table(paths.sample_path(pilot["sample_id"]))
    stratum_of = dict(
        zip(
            sample.column("comment_id").to_pylist(),
            sample.column("stratum").to_pylist(),
            strict=True,
        )
    )
    design = _design(run_id, pilot)
    sections = [
        ("Run", _sec_run(run_id, pilot)),
        ("Cost", _sec_cost(run_id)),
        ("Tokens per call", _sec_tokens(run_id, stratum_of)),
        ("Firsthand rate per design stratum",
         _sec_firsthand(run_id, stratum_of, design)),
        ("Latency", _sec_latency(run_id)),
        ("Answer distributions", _sec_distributions(run_id)),
        ("Screen gate preview", _sec_gate(run_id)),
        ("Packed experiment", _sec_packed(run_id)),
        ("Injected cases", _sec_injected(run_id)),
        ("Projection", _sec_projection(design)),
        ("Calibration", _sec_calibration(run_id)),
    ]
    out = [f"# Pilot report `{run_id}`", ""]
    for title, body in sections:
        out += [f"## {title}", "", *body, ""]
    return "\n".join(out)

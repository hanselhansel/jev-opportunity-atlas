"""Evaluation reports for the audit label sets.

``evaluate_assignment_audit`` measures how often the labeler says a shown
card fits, split by whether the card was the model's pick or a random
group-mate (from the queue's hidden draw). ``evaluate_facet_audit`` measures
per-facet precision and recall of the model's nouls at 0.5 against the
labels. Both weight labeled items by 1/draw-rate and bootstrap by band.
"""

from __future__ import annotations

import numpy as np

from atlas.evaluation import audit_queues, exclusions
from atlas.evaluation.metrics import binary_metrics, choice_confusion
from atlas.evaluation.queue import load_queue, queue_path, read_answers
from atlas.evaluation.store import labels_path, repeats_path

TARGET = 0.75
WEIGHTING = "1/rate[band]"
INTERVAL = "stratified bootstrap by band, 95% percentile"


def _bands(queue: dict):
    band_of = {
        int(c): b
        for b, info in queue.get("bands", {}).items()
        for c in info["ids"]
    }
    rates = {b: float(r) for b, r in queue.get("rates", {}).items()}
    return band_of, rates


def _boot_inputs(cids: list[int], band_of: dict, rates: dict):
    w = np.array(
        [1.0 / rates[band_of[c]] for c in cids], dtype=float
    ) if band_of else np.ones(len(cids))
    strata = [band_of[c] for c in cids] if band_of else None
    return w, strata


def _agreement(primary: dict, repeats: dict, question_id: str) -> dict:
    pairs = [
        (row["value"], repeats[key]["value"])
        for key, row in primary.items()
        if key[1] == question_id and key in repeats
    ]
    agree = sum(a == b for a, b in pairs)
    return {
        "n": len(pairs),
        "agreement": agree / len(pairs) if pairs else None,
    }


def _precision(y, w, strata, n_boot: int, seed: int) -> dict:
    """Share of positive labels, weighted, with a band-stratified bootstrap."""
    if not len(y):
        return {"precision": None, "ci": None}
    m = binary_metrics(
        y, np.ones(len(y)), 0.5,
        weights=w, strata=strata, n_boot=n_boot, seed=seed,
    )
    return {"precision": m["precision"], "ci": m["precision_ci"]}


def _common(label_set: str, run_id: str):
    qpath = queue_path(label_set)
    if not qpath.exists():
        raise ValueError(f"no {label_set} queue at {qpath}")
    queue = load_queue(qpath)
    report = {
        "label_set": label_set,
        "run_id": run_id,
        "queue_run_id": queue.get("run_id"),
        "weighting": WEIGHTING,
        "interval": INTERVAL,
    }
    if queue.get("run_id") != run_id:
        report["warning"] = (
            f"queue was built for run {queue.get('run_id')}, "
            f"not {run_id}"
        )
    return queue, report


def evaluate_assignment_audit(run_id: str, n_boot: int = 2000,
                              seed: int = 0) -> dict:
    queue, report = _common("assignment_audit", run_id)
    band_of, rates = _bands(queue)
    unseen = queue.get("hidden", {})
    primary, excluded = exclusions.latest(labels_path(), "assignment_audit")
    repeats = exclusions.latest(repeats_path(), "assignment_audit")[0]
    labels = {
        cid: row["value"]
        for (cid, q), row in primary.items()
        if q == "fits"
    }

    def _group(want_jev: bool) -> dict:
        cids = [
            cid
            for cid in queue["ids"]
            if cid in labels
            and str(cid) in unseen
            and bool(unseen[str(cid)]["is_jev"]) == want_jev
        ]
        rows = [c for c in cids if labels[c] != "unsure"]
        w, strata = _boot_inputs(rows, band_of, rates)
        y_lenient = np.array(
            [labels[c] in ("yes", "partly") for c in rows], dtype=int
        )
        y_strict = np.array([labels[c] == "yes" for c in rows], dtype=int)
        return {
            "n": len(cids),
            "n_unsure": len(cids) - len(rows),
            "n_forced": sum(
                bool(unseen[str(c)].get("forced")) for c in cids
            ),
            "lenient": _precision(y_lenient, w, strata, n_boot, seed),
            "strict": _precision(y_strict, w, strata, n_boot, seed),
        }

    jev = _group(True)
    random = _group(False)
    report["groups"] = {"jev": jev, "random": random}
    report["gap"] = {
        k: (
            jev[k]["precision"] - random[k]["precision"]
            if jev[k]["precision"] is not None
            and random[k]["precision"] is not None
            else None
        )
        for k in ("lenient", "strict")
    }
    report["agreement"] = {"fits": _agreement(primary, repeats, "fits")}
    report.update(excluded)
    report["target"] = TARGET
    report["meets_target"] = {
        k: (
            None
            if jev[k]["precision"] is None
            else jev[k]["precision"] >= TARGET
        )
        for k in ("lenient", "strict")
    }
    return report


def evaluate_facet_audit(run_id: str, n_boot: int = 2000,
                         seed: int = 0) -> dict:
    queue, report = _common("facet_audit", run_id)
    band_of, rates = _bands(queue)
    primary, excluded = exclusions.latest(labels_path(), "facet_audit")
    repeats = exclusions.latest(repeats_path(), "facet_audit")[0]

    facets: dict[str, dict] = {}
    for qid in audit_queues.FACET_QUESTIONS:
        answers = read_answers(run_id, qid)
        labels = {
            cid: row["value"]
            for (cid, q), row in primary.items()
            if q == qid
        }
        joined = [
            c
            for c in labels
            if answers.get(c, {}).get("noul") is not None
            and (not band_of or c in band_of)
        ]
        rows = [c for c in joined if labels[c] != "unsure"]
        entry = {
            "n": len(rows),
            "n_unsure": len(joined) - len(rows),
            "precision": None,
            "precision_ci": None,
            "recall": None,
            "recall_ci": None,
        }
        if rows:
            y = np.array([labels[c] == "yes" for c in rows], dtype=int)
            score = np.array(
                [answers[c]["noul"] for c in rows], dtype=float
            )
            w, strata = _boot_inputs(rows, band_of, rates)
            m = binary_metrics(
                y, score, 0.5,
                weights=w, strata=strata, n_boot=n_boot, seed=seed,
            )
            entry.update(
                precision=m["precision"],
                precision_ci=m["precision_ci"],
                recall=m["recall"],
                recall_ci=m["recall_ci"],
            )
        facets[qid] = entry

    answers = read_answers(run_id, "resolution")
    pairs = [
        (row["value"], answers[cid]["choice"])
        for (cid, q), row in primary.items()
        if q == "resolution"
        and answers.get(cid, {}).get("choice") is not None
    ]
    report["facets"] = facets
    report["resolution"] = (
        choice_confusion(*zip(*pairs, strict=True))
        if pairs
        else choice_confusion([], [])
    )
    report["agreement"] = {
        q: _agreement(primary, repeats, q)
        for q in (*audit_queues.FACET_QUESTIONS, "resolution")
    }
    report.update(excluded)
    return report

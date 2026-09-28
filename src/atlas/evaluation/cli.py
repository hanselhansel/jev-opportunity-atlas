"""`atlas label` and `atlas eval` commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from atlas import paths
from atlas.evaluation.queue import (
    DEFAULT_BAND_SIZES,
    DEFAULT_BANDS,
    build_queue,
    domain_subset,
    labeling_frame,
    load_queue,
    queue_path,
    read_answers,
    save_queue,
    top_up,
)
from atlas.evaluation.store import LabelStore, labels_path, repeats_path


def _rubric_status() -> str:
    path = paths.CONFIGS / "rubric.v1.md"
    if not path.exists():
        return "missing"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return "missing"
    for line in text.split("---", 2)[1].splitlines():
        if line.strip().startswith("status:"):
            return line.split(":", 1)[1].strip()
    return "missing"


def _default_snapshot() -> str:
    with (paths.CONFIGS / "acquisition.toml").open("rb") as fh:
        return tomllib.load(fh)["snapshot_id"]


def _other_queue_ids(skip: Path) -> set[int]:
    directory = paths.LABELS / "queues"
    ids: set[int] = set()
    if directory.is_dir():
        for file in sorted(directory.glob("*.json")):
            if file != skip:
                ids.update(load_queue(file).get("ids", []))
    return ids


def _summarize(label_set: str, queue: dict) -> str:
    parts = [f"queue {label_set}: {len(queue['ids'])} ids"]
    if queue["bands"]:
        parts.append(
            "(" + " ".join(
                f"{name}={len(b['ids'])}" for name, b in queue["bands"].items()
            ) + ")"
        )
    parts.append(f"{len(queue['repeats'])} repeats")
    return " ".join(parts)


def _label_run(args: argparse.Namespace) -> None:
    status = _rubric_status()
    if status != "approved":
        print(
            f"rubric configs/rubric.v1.md is not approved (status: {status}); "
            "label run refuses to start",
            file=sys.stderr,
        )
        raise SystemExit(1)
    snapshot = args.snapshot or _default_snapshot()
    frame = labeling_frame(args.sample, args.run)
    qpath = queue_path(args.label_set)
    if qpath.exists():
        queue = load_queue(qpath)
        if args.top_up:
            if not queue["bands"]:
                print("top-up needs a banded queue", file=sys.stderr)
                raise SystemExit(1)
            queue = top_up(queue, frame, args.top_up)
            save_queue(queue, qpath)
            print(_summarize(args.label_set, queue))
        else:
            print(f"reusing queue {qpath} ({len(queue['ids'])} ids)")
    else:
        exclude = _other_queue_ids(qpath)
        if args.label_set == "calibration":
            queue = build_queue(
                frame, None, args.seed, exclude, DEFAULT_BANDS, DEFAULT_BAND_SIZES
            )
            domain_ids = domain_subset(queue["ids"], args.seed)
        else:
            if args.n is None:
                print(
                    f"label run --label-set {args.label_set} requires --n",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            queue = build_queue(frame, args.n, args.seed, exclude)
            domain_ids = []
        queue.update(
            {
                "label_set": args.label_set,
                "snapshot_id": snapshot,
                "sample_id": args.sample,
                "run_id": args.run,
                "question_id": "firsthand_problem",
                "created_at": datetime.now(UTC).isoformat(),
                "top_ups": [],
                "domain_ids": domain_ids,
            }
        )
        save_queue(queue, qpath)
        print(_summarize(args.label_set, queue))
    if args.no_launch:
        return
    app = Path(__file__).resolve().with_name("labeler_app.py")
    env = os.environ | {
        "ATLAS_LABEL_SET": args.label_set,
        "ATLAS_QUEUE_PATH": str(qpath),
        "ATLAS_SNAPSHOT_ID": snapshot,
        "ATLAS_REVIEWER": args.reviewer,
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app),
            "--server.headless",
            "true",
        ],
        env=env,
        check=False,
    )


MIN_JOIN_COVERAGE = 0.95
MIN_CALIBRATION_YES = 40
CALIBRATION_NOTE = "calibration only; not a reported quality number"


class CoverageError(Exception):
    pass


def _load_texts(snapshot_id: str, ids: list[int]) -> dict[int, str]:
    from atlas.sources.items import load_items

    items = load_items(paths.snapshot_dir(snapshot_id), ids)
    return {int(i["comment_id"]): i["comment"] or "" for i in items}


def _design(sample_id: str | None) -> tuple[dict, dict]:
    """(weight, story_id) per comment from the probability sample, if it exists."""
    if not sample_id or not paths.sample_path(sample_id).exists():
        return {}, {}
    t = pq.read_table(paths.sample_path(sample_id), columns=["comment_id", "weight", "story_id"])
    ids = t["comment_id"].to_pylist()
    return dict(zip(ids, t["weight"].to_pylist(), strict=True)), dict(
        zip(ids, t["story_id"].to_pylist(), strict=True))


def _agreement(primary: dict, repeats: dict, question_id: str) -> dict:
    pairs = [(row["value"], repeats[key]["value"]) for key, row in primary.items()
             if key[1] == question_id and key in repeats]
    agree = sum(a == b for a, b in pairs)
    return {"n": len(pairs), "agreement": agree / len(pairs) if pairs else None}


def evaluate(label_set: str, run_id: str, question: str = "firsthand_problem",
             target_recall: float = 0.9, snapshot_id: str | None = None,
             n_boot: int = 2000, seed: int = 0) -> dict:
    from atlas.evaluation import metrics
    from atlas.evaluation.baseline import keyword_score

    qpath = queue_path(label_set)
    queue = load_queue(qpath) if qpath.exists() else {}
    band_of = {cid: name for name, b in queue.get("bands", {}).items() for cid in b["ids"]}
    rates = queue.get("rates", {})
    design_w, story_of = _design(queue.get("sample_id"))
    primary = LabelStore(labels_path()).latest(label_set)
    labels = {cid: row["value"] for (cid, q), row in primary.items() if q == question}
    answers = read_answers(run_id, question)
    joined = sorted(c for c in labels if answers.get(c, {}).get("noul") is not None)
    coverage = len(joined) / len(labels) if labels else 0.0
    if coverage < MIN_JOIN_COVERAGE:
        raise CoverageError(f"join coverage {coverage:.3f} < {MIN_JOIN_COVERAGE}: "
                            f"{len(labels)} labeled, {len(joined)} with {question} answers in {run_id}")
    outside = [c for c in joined if band_of and c not in band_of]
    rows = [c for c in joined if labels[c] != "unsure" and c not in outside]
    y = np.array([labels[c] == "yes" for c in rows], dtype=int)
    score = np.array([answers[c]["noul"] for c in rows], dtype=float)
    w = np.array([(1.0 / rates[band_of[c]] if band_of else 1.0) * design_w.get(c, 1.0)
                  for c in rows])
    strata = [band_of[c] for c in rows] if band_of else None
    clusters = [story_of.get(c, c) for c in rows] if story_of else None
    boot = {"weights": w, "strata": strata, "clusters": clusters, "n_boot": n_boot, "seed": seed}

    thr = metrics.threshold_for_recall_lb(y, score, target_recall, **boot)
    threshold = thr["threshold"] if thr["threshold"] is not None else 0.5
    report = {
        "label_set": label_set, "run_id": run_id, "question": question,
        "n_labeled": len(labels), "n_joined": len(joined), "join_coverage": coverage,
        "n_outside_queue": len(outside), "n_unsure": sum(labels[c] == "unsure" for c in joined),
        "n_yes": int(y.sum()), "n_no": int(len(y) - y.sum()),
        "weighting": ("1/rate[band]" if band_of else "unweighted")
                     + (" x sample design weight" if design_w else ""),
        "clusters": "story_id" if story_of else "row",
        "threshold": {**thr, "point_threshold_for_recall": metrics.threshold_for_recall(
            y, score, target_recall, weights=w), "note": CALIBRATION_NOTE},
        "metrics": metrics.binary_metrics(y, score, threshold, **boot),
        "reliability_bins": metrics.reliability_bins(y, score, weights=w),
    }
    snapshot = snapshot_id or queue.get("snapshot_id") or _default_snapshot()
    try:
        texts = _load_texts(snapshot, rows)
        kw = np.array([keyword_score(texts.get(c, "")) for c in rows])
        report["baseline"] = {"name": "keyword_v1", **metrics.binary_metrics(y, kw, 0.5, **boot)}
    except ImportError as exc:
        report["baseline"] = {"name": "keyword_v1", "skipped": f"item loader unavailable: {exc}"}
    repeats = LabelStore(repeats_path()).latest(label_set)
    report["intra_rater"] = {q: _agreement(primary, repeats, q)
                             for q in ("firsthand_problem", "account_type")}
    report["choices"] = {}
    for q in ("account_type", "domain"):
        jev = read_answers(run_id, q)
        pairs = [(row["value"], jev[cid]["choice"]) for (cid, qq), row in primary.items()
                 if qq == q and jev.get(cid, {}).get("choice") is not None]
        report["choices"][q] = metrics.choice_confusion(*zip(*pairs, strict=True)) if pairs \
            else metrics.choice_confusion([], [])
    if label_set == "calibration":
        met = report["n_yes"] >= MIN_CALIBRATION_YES
        report["stop_rule"] = {"min_yes": MIN_CALIBRATION_YES, "met": met, "top_up_command": None if met else (
            f"atlas label run --label-set calibration --sample {queue.get('sample_id')} "
            f"--run {queue.get('run_id', run_id)} --top-up 50")}
    return report


def _eval_cmd(args: argparse.Namespace) -> None:
    try:
        report = evaluate(args.label_set, args.run, args.question, args.target_recall,
                          args.snapshot, args.n_boot, args.seed)
    except CoverageError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    out = paths.run_dir(args.run) / f"eval_{args.label_set}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    rule = report.get("stop_rule")
    if rule and not rule["met"]:
        print(f"fewer than {rule['min_yes']} yes labels; top up with: {rule['top_up_command']}",
              file=sys.stderr)
    print(f"wrote {out}", file=sys.stderr)


def register(sub) -> None:
    label = sub.add_parser("label", help="build label queues and launch the labeler")
    label_sub = label.add_subparsers(dest="label_command", required=True)
    run = label_sub.add_parser("run", help="build or reuse a queue, then label")
    run.add_argument(
        "--label-set", required=True, choices=["calibration", "heldout", "edge"]
    )
    run.add_argument("--sample", required=True)
    run.add_argument("--run", required=True)
    run.add_argument("--snapshot", default=None)
    run.add_argument("--n", type=int, default=None)
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--reviewer", default="hansel")
    run.add_argument("--top-up", type=int, default=None)
    run.add_argument("--no-launch", action="store_true")
    run.set_defaults(func=_label_run)

    evaluate = sub.add_parser("eval", help="evaluate Jev against labels")
    eval_sub = evaluate.add_subparsers(dest="eval_command", required=True)
    erun = eval_sub.add_parser("run")
    erun.add_argument("--label-set", required=True)
    erun.add_argument("--run", required=True)
    erun.add_argument("--question", default="firsthand_problem")
    erun.add_argument("--target-recall", type=float, default=0.9)
    erun.add_argument("--snapshot", default=None)
    erun.add_argument("--n-boot", type=int, default=2000)
    erun.add_argument("--seed", type=int, default=0)
    erun.set_defaults(func=_eval_cmd)

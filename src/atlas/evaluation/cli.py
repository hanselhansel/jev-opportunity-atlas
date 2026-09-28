"""`atlas label` and `atlas eval` commands."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from atlas import paths
from atlas.evaluation.queue import (
    DEFAULT_BAND_SIZES,
    DEFAULT_BANDS,
    build_queue,
    domain_subset,
    labeling_frame,
    load_queue,
    queue_path,
    save_queue,
    top_up,
)


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


def _eval_cmd(args: argparse.Namespace) -> None:
    raise NotImplementedError


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

"""Packed-call experiment: k comments per Jev call vs one comment per call.

Packed items carry their own ``state`` ({"c1": text, ...}) and ``questions``
(``c{j}_firsthand_problem``, the screen wording with ``comment`` rewritten to
the slot), so the runner's per-item path is used verbatim. The synthetic
``packed_question_set(k)`` exists only for the run manifest label and hash.
"""

from __future__ import annotations

import copy
import hashlib
import re

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.inference.ledger import read_rows
from atlas.inference.questions import QuestionSet, load_question_set
from atlas.pilot import stages

PACKED_NAME = "packed-screen"
PACKED_VERSION = 1
PACKED_LABEL = f"{PACKED_NAME}@{PACKED_VERSION}"

PACKED_MAP = pa.schema(
    [
        ("packed_id", pa.int64()),
        ("slot", pa.string()),
        ("comment_id", pa.int64()),
    ]
)
UNPACKED = pa.schema(
    [
        ("comment_id", pa.int64()),
        ("question_id", pa.string()),
        ("noul", pa.float64()),
    ]
)

_SLOT_QID = re.compile(r"^c(\d+)_(.+)$")


def _slot_question(question: dict, slot: str) -> dict:
    """Deep copy of a question with every `comment` reference -> `c{j}`."""
    q = copy.deepcopy(question)
    if isinstance(q.get("instructions"), str):
        q["instructions"] = q["instructions"].replace("`comment`", f"`{slot}`")
    criteria = q.get("criteria")
    if isinstance(criteria, dict):
        q["criteria"] = {
            key: (
                value.replace("`comment`", f"`{slot}`")
                if isinstance(value, str)
                else value
            )
            for key, value in criteria.items()
        }
    return q


def packed_question_set(
    k: int, name: str = "screen", version: int = 1
) -> QuestionSet:
    """Synthetic set carrying the packed questions; run_batch uses its label
    and sha256 while items supply their own state/questions."""
    screen = load_question_set(name, version)
    label = f"packed-{name}@{version}"
    return QuestionSet(
        name=f"packed-{name}",
        version=version,
        label=label,
        state_fields=[f"c{j}" for j in range(1, k + 1)],
        questions={
            f"c{j}_firsthand_problem": _slot_question(
                screen.questions["firsthand_problem"], f"c{j}"
            )
            for j in range(1, k + 1)
        },
        sha256=hashlib.sha256(f"{screen.sha256}:k={k}".encode()).hexdigest(),
    )


def packed_items(
    items: list[dict], k: int = 5, name: str = "screen", version: int = 1
) -> tuple[list[dict], pa.Table]:
    """Chunk items k at a time into packed items plus a packed_id/slot map."""
    base = load_question_set(name, version).questions["firsthand_problem"]
    packed: list[dict] = []
    map_rows: list[dict] = []
    for i in range(0, len(items), k):
        chunk = items[i : i + k]
        packed_id = int(chunk[0]["comment_id"])
        state: dict = {}
        questions: dict = {}
        members: list[int] = []
        for j, item in enumerate(chunk, start=1):
            slot = f"c{j}"
            cid = int(item["comment_id"])
            state[slot] = item["comment"]
            questions[f"{slot}_firsthand_problem"] = _slot_question(base, slot)
            members.append(cid)
            map_rows.append(
                {"packed_id": packed_id, "slot": slot, "comment_id": cid}
            )
        packed.append(
            {
                "comment_id": packed_id,
                "state": state,
                "questions": questions,
                "members": members,
            }
        )
    return packed, pa.Table.from_pylist(map_rows, schema=PACKED_MAP)


def unpack_answers(answers: pa.Table, packed_map: pa.Table) -> pa.Table:
    """Map each (packed_id, "c{j}_<qid>") answer back to its member comment."""
    members = {
        (r["packed_id"], r["slot"]): r["comment_id"]
        for r in packed_map.to_pylist()
    }
    rows = []
    for r in answers.to_pylist():
        m = _SLOT_QID.match(r["question_id"] or "")
        if m is None:
            continue
        rows.append(
            {
                "comment_id": members[(r["comment_id"], f"c{m.group(1)}")],
                "question_id": m.group(2),
                "noul": r["noul"],
            }
        )
    return pa.Table.from_pylist(rows, schema=UNPACKED)


def ledger_tokens(ledger_path, question_set, comment_ids=None) -> float:
    """Sum input_tokens over `calculated` rows for one question set,
    optionally restricted to a set of comment ids."""
    ids = None if comment_ids is None else {int(c) for c in comment_ids}
    total = 0
    for row in read_rows(ledger_path):
        if row.get("cost_class") != "calculated":
            continue
        if row.get("question_set") != question_set:
            continue
        if ids is not None and row.get("comment_id") not in ids:
            continue
        total += row.get("input_tokens") or 0
    return float(total)


def _firsthand_nouls(table: pa.Table) -> dict[int, float]:
    out = {}
    for r in table.to_pylist():
        if r["question_id"] == "firsthand_problem" and r["noul"] is not None:
            out[int(r["comment_id"])] = float(r["noul"])
    return out


def compare_packed(
    single_answers: pa.Table,
    unpacked: pa.Table,
    *,
    single_ledger=None,
    packed_ledger=None,
    packed_map=None,
) -> dict:
    """Agreement between single-call and packed-call firsthand nouls, matched
    on comment_id, plus per-comment token costs when ledgers are given."""
    single = _firsthand_nouls(single_answers)
    packed_scores = _firsthand_nouls(unpacked)
    matched = sorted(set(single) & set(packed_scores))
    n = len(matched)
    s = np.array([single[c] for c in matched])
    p = np.array([packed_scores[c] for c in matched])
    pearson = None
    if n >= 2 and s.std() > 0 and p.std() > 0:
        pearson = float(np.corrcoef(s, p)[0, 1])
    single_tokens = packed_tokens = None
    if single_ledger is not None and n:
        single_tokens = ledger_tokens(single_ledger, "screen@1", matched) / n
    if (
        packed_ledger is not None
        and packed_map is not None
        and packed_map.num_rows
    ):
        packed_tokens = (
            ledger_tokens(packed_ledger, PACKED_LABEL) / packed_map.num_rows
        )
    return {
        "n": n,
        "pearson": pearson,
        "agreement_at_0_5": (
            float(np.mean((s >= 0.5) == (p >= 0.5))) if n else None
        ),
        "mean_abs_diff": float(np.mean(np.abs(s - p))) if n else None,
        "tokens_per_comment": {
            "single": single_tokens,
            "packed": packed_tokens,
        },
    }


def run_packed(run_id, n=500, k=5, seed=1, budget="pilot", yes=False) -> dict:
    """Run the packed screen over a seeded subset of the pilot sample.

    ``run_id`` is the base pilot run (``pilot-<seed>``); the experiment writes
    its own run directory ``<run_id>-packed`` with the packed map and answers.
    """
    from atlas.sources.items import load_items

    pilot = stages.read_pilot_json(run_id)
    sample = pq.read_table(paths.sample_path(pilot["sample_id"]))
    ids = sorted(int(c) for c in sample.column("comment_id").to_pylist())
    rng = np.random.default_rng(seed)
    subset = sorted(
        int(c) for c in rng.choice(ids, size=min(n, len(ids)), replace=False)
    )
    items = load_items(paths.snapshot_dir(pilot["snapshot_id"]), subset)
    packed_list, packed_map = packed_items(items, k=k)
    qs = packed_question_set(k)
    est = stages.estimate(packed_list, qs, budget)
    stages.print_estimate(est)
    if not yes:
        return {"estimate": est, "dispatched": False}
    packed_run = f"{run_id}-packed"
    run_dir = paths.run_dir(packed_run)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(packed_map, run_dir / "packed_map.parquet")
    out = stages.dispatch(packed_run, packed_list, qs, budget)
    return {"estimate": est, "dispatched": True, "run": out}

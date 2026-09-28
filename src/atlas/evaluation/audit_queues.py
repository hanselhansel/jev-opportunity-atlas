"""Audit label queues for the L16 labeler modes.

Each builder draws items with known selection probabilities, saves a blinded
queue (display fields in ``items``, never-show fields in ``hidden``), and
writes contract GOLD_DRAWS rows via ``atlas.pilot.gold._write_gold``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.cards.engine.assign import load_assignments
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.merge import pair_id
from atlas.evaluation.queue import (
    _allocate,
    build_queue,
    queue_path,
    save_queue,
)
from atlas.pilot.gold import _write_gold

FACET_QUESTIONS = (
    "workaround",
    "paid",
    "switched",
    "abandoned",
    "cost_time",
    "cost_money",
)
CONFIDENCE_BANDS = {"high": (0.5, 1.01), "low": (0.0, 0.5)}
MERGE_BANDS = {
    "same": (1.5, 2.01),
    "related": (0.5, 1.5),
    "different": (0.0, 0.5),
}
SHOW_PROB = 0.5


def card_item_id(version: str, card_id: str) -> int:
    """Stable int64 item id for a card in the interview queue."""
    return int(
        hashlib.sha256(f"{version}:card:{card_id}".encode()).hexdigest()[:15],
        16,
    )


def write_gold(rows: list[dict], label_set: str):
    """Validate audit gold rows, then replace this label set's rows.

    ``selection_prob`` may be None only for ``interview`` rows with purpose
    ``audit`` (a judgment queue, not a probability draw); every other row
    needs a float in (0, 1].
    """
    for row in rows:
        if row["label_set"] != label_set:
            raise ValueError(
                f"gold row label_set {row['label_set']!r} != {label_set!r}"
            )
        if row["purpose"] not in ("estimate", "calibration", "audit"):
            raise ValueError(f"unknown gold purpose {row['purpose']!r}")
        prob = row["selection_prob"]
        if prob is None:
            if not (label_set == "interview" and row["purpose"] == "audit"):
                raise ValueError(
                    "selection_prob may be null only for interview audits"
                )
        elif not isinstance(prob, float) or not 0 < prob <= 1:
            raise ValueError(f"bad selection_prob {prob!r}")
    return _write_gold(rows, {label_set})


def _stamp(queue: dict, label_set: str, items: dict, hidden: dict) -> dict:
    queue.update(
        {
            "label_set": label_set,
            "items": items,
            "hidden": hidden,
            "created_at": datetime.now(UTC).isoformat(),
            "top_ups": [],
        }
    )
    return queue


def _banded_gold(queue: dict, label_set: str) -> list[dict]:
    """One gold row per drawn id; the band name is the draw stratum."""
    band_of = {
        int(c): b for b, info in queue["bands"].items() for c in info["ids"]
    }
    return [
        {
            "label_set": label_set,
            "comment_id": int(cid),
            "draw_stratum": band_of[int(cid)],
            "selection_prob": float(queue["rates"][band_of[int(cid)]]),
            "seed": int(queue["seed"]),
            "purpose": "audit",
        }
        for cid in queue["ids"]
    ]


def _band_sizes(n: int, bands) -> dict[str, int]:
    if len(bands) == 2:
        return {"high": n - n // 2, "low": n // 2}
    return dict(zip(bands, _allocate(n, [1] * len(bands)), strict=True))


def _scores_table(scores: dict[int, float]) -> pa.Table:
    ids = sorted(scores)
    return pa.table(
        {
            "comment_id": pa.array(ids, type=pa.int64()),
            "score": pa.array([scores[c] for c in ids], type=pa.float64()),
        }
    )


def facet_audit_queue(run_id: str, n: int = 150, seed: int = 1, *,
                      snapshot_id: str | None = None) -> dict:
    """Half the queue from comments with max facet noul >= 0.5, half below."""
    scores: dict[int, float] = {}
    directory = paths.run_dir(run_id) / "answers"
    if directory.is_dir():
        for file in sorted(directory.glob("part-*.parquet")):
            table = pq.read_table(
                file,
                columns=["comment_id", "question_set", "question_id", "noul"],
            )
            for cid, qset, qid, noul in zip(
                table.column("comment_id").to_pylist(),
                table.column("question_set").to_pylist(),
                table.column("question_id").to_pylist(),
                table.column("noul").to_pylist(),
                strict=True,
            ):
                if qset != "facets@1" or qid not in FACET_QUESTIONS:
                    continue
                if noul is not None:
                    cid = int(cid)
                    scores[cid] = max(noul, scores.get(cid, 0.0))
    queue = build_queue(
        _scores_table(scores),
        None,
        seed,
        frozenset(),
        CONFIDENCE_BANDS,
        _band_sizes(n, CONFIDENCE_BANDS),
        repeat_share=0.10,
    )
    _stamp(
        queue,
        "facet_audit",
        {str(c): {"comment_id": int(c)} for c in queue["ids"]},
        {},
    )
    queue.update(
        run_id=run_id, snapshot_id=snapshot_id, question_set="facets@1"
    )
    save_queue(queue, queue_path("facet_audit"))
    write_gold(_banded_gold(queue, "facet_audit"), "facet_audit")
    return queue


def _active_jev_card(row: dict, cs) -> str | None:
    """The resolved card for an assignment row, or None when unusable."""
    card_id = row.get("card_id")
    if card_id in (None, "none"):
        return None
    try:
        resolved = cs.resolve(card_id)
    except ValueError:
        return None
    return resolved if resolved in cs.cards else None


def _pain_texts(run_dir) -> dict[int, str]:
    path = run_dir / "pain.parquet"
    if not path.exists():
        return {}
    return {
        int(r["comment_id"]): r["pain_sentence"]
        for r in pq.read_table(path).to_pylist()
    }


def assignment_audit_queue(assign_run_id: str, taxonomy_version: str,
                           n: int = 200, seed: int = 1, *,
                           cardset: str) -> dict:
    """Stratifies on card_confidence; half the shown cards are Jev's pick,
    half a random other active card in the same group (hidden)."""
    cs = load_cardset(cardset, taxonomy_version)
    run_dir = paths.run_dir(assign_run_id)
    pain = _pain_texts(run_dir)
    scores: dict[int, float] = {}
    jev_of: dict[int, str] = {}
    for row in load_assignments(run_dir, taxonomy_version).rows:
        cid = int(row["comment_id"])
        if row.get("card_confidence") is None or not pain.get(cid):
            continue
        jev = _active_jev_card(row, cs)
        if jev is None:
            continue
        scores[cid] = float(row["card_confidence"])
        jev_of[cid] = jev
    queue = build_queue(
        _scores_table(scores),
        None,
        seed,
        frozenset(),
        CONFIDENCE_BANDS,
        _band_sizes(n, CONFIDENCE_BANDS),
        repeat_share=0.10,
    )
    show_seed = seed + 16
    rng = np.random.default_rng(show_seed)
    items: dict[str, dict] = {}
    hidden: dict[str, dict] = {}
    for cid in sorted(queue["ids"]):
        jev = jev_of[cid]
        group = cs.cards[jev].group_id
        alts = sorted(c.card_id for c in cs.cards_in(group)
                      if c.card_id != jev)
        if not alts:
            shown, forced = jev, True
        else:
            forced = False
            if rng.random() < SHOW_PROB:
                shown = jev
            else:
                shown = alts[int(rng.integers(len(alts)))]
        hidden[str(cid)] = {
            "jev_card_id": jev,
            "shown_card_id": shown,
            "is_jev": shown == jev,
            "forced": forced,
        }
        items[str(cid)] = {
            "comment_id": cid,
            "pain_sentence": pain[cid],
            "card_statement": cs.cards[shown].statement,
        }
    _stamp(queue, "assignment_audit", items, hidden)
    queue.update(
        {
            "run_id": assign_run_id,
            "taxonomy_version": taxonomy_version,
            "cardset": cardset,
            "show_seed": show_seed,
            "show_prob": SHOW_PROB,
        }
    )
    save_queue(queue, queue_path("assignment_audit"))
    write_gold(_banded_gold(queue, "assignment_audit"), "assignment_audit")
    return queue


def merge_audit_queue(scored_pairs: list[dict], n: int = 50, seed: int = 1, *,
                      taxonomy_version: str, cardset: str) -> dict:
    """Bands on Jev's expected merge score (0..2); items show statements only."""
    cs = load_cardset(cardset, taxonomy_version)
    by_id: dict[int, dict] = {}
    scores: dict[int, float] = {}
    for pair in scored_pairs:
        a, b = pair["card_a"], pair["card_b"]
        pid = pair_id(taxonomy_version, a, b)
        by_id[pid] = pair
        scores[pid] = float(pair["expected"])
    queue = build_queue(
        _scores_table(scores),
        None,
        seed,
        frozenset(),
        MERGE_BANDS,
        _band_sizes(n, MERGE_BANDS),
        repeat_share=0.0,
    )
    items: dict[str, dict] = {}
    hidden: dict[str, dict] = {}
    for cid in queue["ids"]:
        pair = by_id[cid]
        items[str(cid)] = {
            "card_a": cs.all_cards[pair["card_a"]].statement,
            "card_b": cs.all_cards[pair["card_b"]].statement,
        }
        hidden[str(cid)] = {
            "card_a": pair["card_a"],
            "card_b": pair["card_b"],
            "expected": float(pair["expected"]),
        }
    _stamp(queue, "merge_audit", items, hidden)
    queue.update({"taxonomy_version": taxonomy_version, "cardset": cardset})
    save_queue(queue, queue_path("merge_audit"))
    write_gold(_banded_gold(queue, "merge_audit"), "merge_audit")
    return queue


def interview_queue(card_metrics: pa.Table, top_k: int = 200, *,
                    taxonomy_version: str, cardset: str,
                    examples: dict[str, list[str]] | None = None,
                    seed: int = 1) -> dict:
    """Top-k cards by score (or n_authors fallback). A judgment queue, not a
    probability draw: gold rows carry a null selection_prob."""
    cs = load_cardset(cardset, taxonomy_version)
    key = "score" if "score" in card_metrics.column_names else "n_authors"
    ranked = sorted(
        (r for r in card_metrics.to_pylist() if r["card_id"] in cs.cards),
        key=lambda r: (
            r[key] is None,
            -r[key] if r[key] is not None else 0.0,
            r["card_id"],
        ),
    )[:top_k]
    rng = np.random.default_rng(seed)
    items: dict[str, dict] = {}
    hidden: dict[str, dict] = {}
    ids: list[int] = []
    for row in ranked:
        card_id = row["card_id"]
        cid = card_item_id(taxonomy_version, card_id)
        ids.append(cid)
        pool = sorted(examples.get(card_id, [])) if examples else []
        drawn = rng.choice(len(pool), size=min(5, len(pool)), replace=False)
        picked = [pool[int(i)] for i in drawn]
        card = cs.all_cards[card_id]
        items[str(cid)] = {
            "statement": card.statement,
            "group_label": cs.groups[card.group_id],
            "examples": picked,
            "metrics": {
                "authors": row.get("n_authors"),
                "threads": row.get("n_threads"),
                "periods": row.get("n_periods"),
                "domains": row.get("n_domains"),
            },
        }
        hidden[str(cid)] = {"card_id": card_id}
    queue = {
        "label_set": "interview",
        "ids": ids,
        "repeats": [],
        "bands": {},
        "rates": {},
        "seed": int(seed),
        "items": items,
        "hidden": hidden,
        "created_at": datetime.now(UTC).isoformat(),
        "top_ups": [],
        "taxonomy_version": taxonomy_version,
        "cardset": cardset,
        "top_k": top_k,
    }
    save_queue(queue, queue_path("interview"))
    write_gold(
        [
            {
                "label_set": "interview",
                "comment_id": int(cid),
                "draw_stratum": "top_k",
                "selection_prob": None,
                "seed": int(seed),
                "purpose": "audit",
            }
            for cid in ids
        ],
        "interview",
    )
    return queue


def interview_examples(assign_run_id: str, taxonomy_version: str,
                       cardset: str, min_card_p: float = 0.5,
                       ) -> dict[str, list[str]]:
    """card_id -> pain sentences from assignments with card_p >= min_card_p
    and a resolvable active card."""
    cs = load_cardset(cardset, taxonomy_version)
    run_dir = paths.run_dir(assign_run_id)
    pain = _pain_texts(run_dir)
    out: dict[str, list[str]] = {}
    for row in load_assignments(run_dir, taxonomy_version).rows:
        card_p = row.get("card_p")
        if card_p is None or card_p < min_card_p:
            continue
        card_id = _active_jev_card(row, cs)
        if card_id is None:
            continue
        text = pain.get(int(row["comment_id"]))
        if text:
            out.setdefault(card_id, []).append(text)
    return out

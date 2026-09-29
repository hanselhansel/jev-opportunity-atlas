"""Two-level need assignment through the batch runner.

Level 1 asks which group a comment's pain sentence belongs to; level 2 asks
which card inside the chosen group it expresses. Both carry a `none` option.
Question-set labels embed the taxonomy version (`assign-g@t0`) so the ledger,
cache, and manifest stay versioned. Results are contract ASSIGNMENTS rows plus
per-comment metadata used by merge detection and reporting.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts
from atlas.inference.questions import QuestionSet, canonical_json
from atlas.inference.runner import raise_for_stopped, run_batch

NONE = "none"
GROUP_NONE_TEXT = "none of these groups fits"
CARD_NONE_TEXT = "none of these needs fits"
LOW_CONFIDENCE = 0.5
MAX_GROUP_WORDS = 8
MAX_CARD_WORDS = 20

GROUP_INSTRUCTIONS = (
    "Which group of needs does `problem` belong to? "
    "`sentences` is the whole comment, for context."
)
CARD_INSTRUCTIONS = "Which need does `problem` express?"


def _n_words(text: str) -> int:
    return len(text.split())


def check_lengths(cs) -> None:
    """Criteria text is paid on every call; keep it short."""
    from atlas.cards.engine.cardset import CardSetError

    for gid, label in cs.groups.items():
        if _n_words(label) > MAX_GROUP_WORDS:
            raise CardSetError(
                f"group {gid!r} label is {_n_words(label)} words "
                f"(max {MAX_GROUP_WORDS})"
            )
    for card in cs.cards.values():
        if _n_words(card.statement) > MAX_CARD_WORDS:
            raise CardSetError(
                f"card {card.card_id!r} statement is "
                f"{_n_words(card.statement)} words (max {MAX_CARD_WORDS})"
            )


def _sentences_state(comment_sentences) -> dict:
    return {
        f"s{i}": s for i, s in enumerate(list(comment_sentences or [])[:255])
    }


def _active_groups(cs) -> list[str]:
    return [gid for gid in cs.groups if cs.cards_in(gid)]


def group_item(
    comment_id, pain_sentence, comment_sentences, cs,
    instructions=GROUP_INSTRUCTIONS,
) -> dict:
    criteria = {gid: cs.groups[gid] for gid in _active_groups(cs)}
    criteria[NONE] = GROUP_NONE_TEXT
    return {
        "comment_id": comment_id,
        "state": {
            "problem": pain_sentence,
            "sentences": _sentences_state(comment_sentences),
        },
        "questions": {
            "group": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }


def card_item(
    comment_id, pain_sentence, sentences, cs, group_id,
    instructions=CARD_INSTRUCTIONS,
) -> dict:
    criteria = {c.card_id: c.statement for c in cs.cards_in(group_id)}
    criteria[NONE] = CARD_NONE_TEXT
    return {
        "comment_id": comment_id,
        "state": {
            "problem": pain_sentence,
            "sentences": _sentences_state(sentences),
        },
        "questions": {
            "card": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        },
    }


def engine_qs(label_name: str, cs, template: dict) -> QuestionSet:
    """A synthetic QuestionSet pinned to the cardset hash and question shape."""
    blob = canonical_json({"cardset": cs.sha256, "questions": template})
    return QuestionSet(
        name=label_name,
        version=cs.version,
        label=f"{label_name}@{cs.version}",
        state_fields=[],
        questions=template,
        sha256=hashlib.sha256(blob.encode("utf-8")).hexdigest(),
    )


def read_answers(run_dir: Path, label: str) -> dict[int, dict[str, dict]]:
    """comment_id -> question_id -> ANSWERS row; later parts win."""
    answers_dir = Path(run_dir) / "answers"
    out: dict[int, dict[str, dict]] = {}
    if not answers_dir.exists():
        return out
    parts = sorted(
        answers_dir.glob("part-*.parquet"),
        key=lambda p: int(p.stem.rsplit("-", 1)[1]),
    )
    for part in parts:
        for row in pq.read_table(part).to_pylist():
            if row["question_set"] != label:
                continue
            out.setdefault(row["comment_id"], {})[row["question_id"]] = row
    return out


@dataclass
class AssignResult:
    rows: list[dict] = field(default_factory=list)  # contract ASSIGNMENTS keys
    meta: dict[int, dict] = field(default_factory=dict)


def _probs(answer: dict) -> dict:
    raw = answer.get("probabilities_json")
    return json.loads(raw) if raw else {}


def _top2(probs: dict) -> list[str]:
    ordered = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in ordered if k != NONE][:2]


async def assign(
    ctx,
    rows,
    cs,
    question_set_prefix="assign",
    group_instructions=GROUP_INSTRUCTIONS,
    card_instructions=CARD_INSTRUCTIONS,
) -> AssignResult:
    rows = list(rows)
    check_lengths(cs)
    gqs = engine_qs(
        f"{question_set_prefix}-g",
        cs,
        {"group": {"type": "choice", "instructions": group_instructions}},
    )
    g_out = await run_batch(
        ctx,
        (
            group_item(
                r["comment_id"], r["pain_sentence"], r["sentences"], cs,
                instructions=group_instructions,
            )
            for r in rows
        ),
        gqs,
    )
    raise_for_stopped(ctx, g_out, len(rows))
    g_answers = read_answers(ctx.run_dir, gqs.label)

    cqs = engine_qs(
        f"{question_set_prefix}-c",
        cs,
        {"card": {"type": "choice", "instructions": card_instructions}},
    )
    level2 = [
        card_item(
            r["comment_id"], r["pain_sentence"], r["sentences"], cs,
            g_answers[r["comment_id"]]["group"]["choice"],
            instructions=card_instructions,
        )
        for r in rows
        if g_answers.get(r["comment_id"], {}).get("group", {}).get("choice")
        not in (None, NONE)
    ]
    if level2:
        c_out = await run_batch(ctx, level2, cqs)
        raise_for_stopped(
            ctx,
            c_out,
            len(level2),
            prior=g_out["completed"] + g_out["skipped_completed"],
        )
    c_answers = read_answers(ctx.run_dir, cqs.label)

    result = AssignResult()
    for r in rows:
        cid = r["comment_id"]
        g = g_answers.get(cid, {}).get("group")
        if g is None or g.get("choice") is None:
            continue  # failed group call: omit
        group_id = g["choice"]
        row = {
            "run_id": ctx.run_id,
            "comment_id": cid,
            "taxonomy_version": cs.version,
            "group_id": group_id,
            "group_p": _probs(g).get(group_id),
            "group_confidence": g.get("confidence"),
            "card_id": None,
            "card_p": None,
            "card_confidence": None,
            "verified_p": None,
        }
        meta = {
            "low_confidence": False,
            "card_top2": [],
            "group_probs": _probs(g),
            "card_probs": {},
        }
        if group_id != NONE:
            c = c_answers.get(cid, {}).get("card")
            if c is None or c.get("choice") is None:
                continue  # level-2 call owed but failed: omit
            cprobs = _probs(c)
            row["card_id"] = c["choice"]
            row["card_p"] = cprobs.get(c["choice"])
            row["card_confidence"] = c.get("confidence")
            meta["card_probs"] = cprobs
            meta["card_top2"] = _top2(cprobs)
            meta["low_confidence"] = (
                row["card_confidence"] is not None
                and row["card_confidence"] < LOW_CONFIDENCE
            )
        result.rows.append(row)
        result.meta[cid] = meta
    return result


def assignments_path(run_dir: Path, version: str) -> Path:
    return Path(run_dir) / f"assignments-{version}.parquet"


def write_assignments(run_dir: Path, result: AssignResult, version: str) -> Path:
    path = assignments_path(run_dir, version)
    table = pa.Table.from_pylist(list(result.rows), schema=contracts.ASSIGNMENTS)
    pq.write_table(table, str(path))
    meta_path = path.with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps({str(k): v for k, v in result.meta.items()}, indent=1) + "\n",
        encoding="utf-8",
    )
    return path


def load_assignments(run_dir: Path, version: str) -> AssignResult:
    path = assignments_path(run_dir, version)
    rows = pq.read_table(path).to_pylist()
    meta_path = path.with_suffix(".meta.json")
    meta = {}
    if meta_path.exists():
        meta = {int(k): v for k, v in json.loads(meta_path.read_text()).items()}
    return AssignResult(rows=rows, meta=meta)


def _is_residue(row: dict) -> bool:
    return row.get("group_id") == NONE or row.get("card_id") == NONE


def _allocate(counts: dict[str, int], k: int) -> dict[str, int]:
    """Proportional largest-remainder allocation, >=1 per stratum when it fits,
    capped at stratum size."""
    strata = sorted(counts)
    n_residue = sum(counts.values())
    total = min(k, n_residue)
    alloc = {g: 0 for g in strata}
    if not strata or total <= 0:
        return alloc
    exact = {g: total * counts[g] / n_residue for g in strata}
    for g in strata:
        alloc[g] = int(exact[g])
    for g in sorted(strata, key=lambda g: (-(exact[g] - alloc[g]), g)):
        if sum(alloc.values()) >= total:
            break
        alloc[g] += 1
    if k >= len(strata):
        for g in strata:
            if alloc[g] < 1:
                donor = max(strata, key=lambda h: (alloc[h], h))
                if alloc[donor] > 1:
                    alloc[donor] -= 1
                alloc[g] = 1
    leftover = 0
    for g in strata:
        if alloc[g] > counts[g]:
            leftover += alloc[g] - counts[g]
            alloc[g] = counts[g]
    while leftover > 0:
        progressed = False
        for g in sorted(strata, key=lambda g: (-(counts[g] - alloc[g]), g)):
            if leftover <= 0:
                break
            if alloc[g] < counts[g]:
                alloc[g] += 1
                leftover -= 1
                progressed = True
        if not progressed:
            break
    return alloc


def residue_sample(assignments: list[dict], k: int, seed: int) -> dict:
    """Seeded stratified sample of residue comment ids (group or card 'none')."""
    rows = list(assignments)
    n_total = len(rows)
    by_group: dict[str, list[dict]] = {}
    for r in rows:
        by_group.setdefault(r["group_id"], []).append(r)
    residue: dict[str, list[int]] = {}
    for g, grows in by_group.items():
        ids = [r["comment_id"] for r in grows if _is_residue(r)]
        if ids:
            residue[g] = sorted(ids)
    n_residue = sum(len(v) for v in residue.values())
    alloc = _allocate({g: len(v) for g, v in residue.items()}, k)
    rng = random.Random(seed)
    sample: list[int] = []
    for g in sorted(residue):
        if alloc.get(g):
            sample.extend(rng.sample(residue[g], alloc[g]))
    return {
        "sample": sample,
        "share": (n_residue / n_total) if n_total else 0.0,
        "share_by_group": {
            g: sum(1 for r in grows if _is_residue(r)) / len(grows)
            for g, grows in by_group.items()
        },
        "n_residue": n_residue,
        "n_total": n_total,
    }

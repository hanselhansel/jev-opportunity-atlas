"""Residue reassignment after an induction round (L26), plus `--scope all`
(L30).

When a cardset grows from a base version to a superset (same groups and group
labels, every base card unchanged, only new cards added), `cards induce`
re-asks the residue at the card level and writes one combined assignments
table. The residue is rows whose base assignment found a real group but
landed on card `none`, a null card, or card_p under LOW_CONFIDENCE; the
group answer is already known, so no group-level call is made (its
question-set label would embed the new version and miss the cache anyway).

`--scope all` re-asks the card level for every base row with a real group,
so rows already on a base card can move to a card added in the new version
(the wave-1 induce / wave-2 direct-assign mix biased card shares). It is
also the only scope allowed when base and new versions are equal, e.g.
re-running a mixed-path combined run under its own version. The card-level
label `assign-c@<version>` is the same for both scopes, so a rerun with a
different scope into the same run directory resumes: rows already answered
are covered by the done set.
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas.cards.engine.assign import (
    CARD_INSTRUCTIONS,
    LOW_CONFIDENCE,
    NONE,
    AssignResult,
    _probs,
    _top2,
    card_item,
    check_lengths,
    engine_qs,
    read_answers,
)
from atlas.cards.engine.cardset import CardSetError
from atlas.inference.runner import run_batch


def check_superset(base_cs, new_cs) -> None:
    """Raise CardSetError unless new_cs is base_cs plus only added cards:
    identical groups and labels, every base card byte-identical."""
    if base_cs.groups != new_cs.groups:
        raise CardSetError(
            f"induce needs identical groups and labels; "
            f"{base_cs.version} -> {new_cs.version} differ"
        )
    for cid, card in base_cs.all_cards.items():
        if new_cs.all_cards.get(cid) != card:
            raise CardSetError(
                f"base card {cid!r} is missing or changed in {new_cs.version}"
            )


def residue(rows, threshold=LOW_CONFIDENCE) -> list[dict]:
    """Rows to re-ask at card level: real group_id, but card_id null/'none'
    or card_p under `threshold`."""
    out = []
    for r in rows:
        if r.get("group_id") in (None, NONE):
            continue
        card_id, card_p = r.get("card_id"), r.get("card_p")
        if card_id in (None, NONE) or (
            card_p is not None and card_p < threshold
        ):
            out.append(r)
    return out


def scoped_rows(rows, scope="residue", threshold=LOW_CONFIDENCE) -> list[dict]:
    """Rows re-asked at card level under `scope`: `residue` is real-group rows
    with card null/'none' or card_p under `threshold`; `all` is every row
    with a real group."""
    if scope == "all":
        return [r for r in rows if r.get("group_id") not in (None, NONE)]
    return residue(rows, threshold)


def scope_items(base_rows, items_by_cid, cs, scope="residue") -> list[dict]:
    """Card-level run_batch items for `scope` rows, against cardset `cs`."""
    items, missing = [], []
    for r in scoped_rows(base_rows, scope):
        it = items_by_cid.get(r["comment_id"])
        if it is None:
            missing.append(r["comment_id"])
            continue
        items.append(
            card_item(
                it["comment_id"],
                it["pain_sentence"],
                it["sentences"],
                cs,
                r["group_id"],
            )
        )
    if missing:
        raise ValueError(
            f"items parquet is missing {len(missing)} comments for "
            f"--scope {scope} (first: {missing[:5]})"
        )
    return items


async def induce(
    ctx, base_result, items_by_cid, cs, scope="residue"
) -> AssignResult:
    """Re-ask the card level for `scope` rows under `assign-c@<cs.version>`;
    every other base row is carried with run_id/taxonomy_version re-stamped."""
    check_lengths(cs)
    res_ids = {
        r["comment_id"] for r in scoped_rows(base_result.rows, scope)
    }
    level2 = scope_items(base_result.rows, items_by_cid, cs, scope)
    cqs = engine_qs(
        "assign-c",
        cs,
        {"card": {"type": "choice", "instructions": CARD_INSTRUCTIONS}},
    )
    if level2:
        await run_batch(ctx, level2, cqs)
    c_answers = read_answers(ctx.run_dir, cqs.label)
    result = AssignResult()
    for r in base_result.rows:
        cid = r["comment_id"]
        if cid not in res_ids:
            result.rows.append(
                {**r, "run_id": ctx.run_id, "taxonomy_version": cs.version}
            )
            result.meta[cid] = base_result.meta.get(cid) or {
                "low_confidence": False,
                "card_top2": [],
                "group_probs": {},
                "card_probs": {},
            }
            continue
        c = c_answers.get(cid, {}).get("card")
        if c is None or c.get("choice") is None:
            continue  # card call owed but failed: omit, same as assign
        cprobs = _probs(c)
        result.rows.append(
            {
                "run_id": ctx.run_id,
                "comment_id": cid,
                "taxonomy_version": cs.version,
                "group_id": r["group_id"],
                "group_p": r["group_p"],
                "group_confidence": r["group_confidence"],
                "card_id": c["choice"],
                "card_p": cprobs.get(c["choice"]),
                "card_confidence": c.get("confidence"),
                "verified_p": None,
            }
        )
        result.meta[cid] = {
            "low_confidence": (
                c.get("confidence") is not None
                and c["confidence"] < LOW_CONFIDENCE
            ),
            "card_top2": _top2(cprobs),
            "group_probs": (base_result.meta.get(cid) or {}).get(
                "group_probs", {}
            ),
            "card_probs": cprobs,
        }
    return result


def _card_key(card_id):
    """None and 'none' both mean unassigned for changed-card counting."""
    return None if card_id in (None, NONE) else card_id


def induce_stats(
    base_cs, new_cs, base_rows, out_rows, run_id, base_run, scope="residue"
) -> dict:
    """Sidecar payload: provenance, scope, carried/reassigned/moved/changed
    counts, and the assigned counts of the cards the induction round added."""
    res_ids = {r["comment_id"] for r in scoped_rows(base_rows, scope)}
    base_card = {
        r["comment_id"]: _card_key(r.get("card_id")) for r in base_rows
    }
    new_counts = {
        cid: 0 for cid in new_cs.cards if cid not in base_cs.all_cards
    }
    reassigned = moved = changed = 0
    for r in out_rows:
        card = r.get("card_id")
        if card in new_counts:
            new_counts[card] += 1
        if r["comment_id"] in res_ids:
            reassigned += 1
            if card not in (None, NONE):
                moved += 1
        if _card_key(card) != base_card.get(r["comment_id"]):
            changed += 1
    return {
        "run_id": run_id,
        "taxonomy_version": new_cs.version,
        "base_run": base_run,
        "base_version": base_cs.version,
        "scope": scope,
        "carried": len(out_rows) - reassigned,
        "reassigned": reassigned,
        "moved_to_card": moved,
        "changed_card": changed,
        "new_card_assignments": new_counts,
    }


def induce_path(run_dir: Path, version: str) -> Path:
    return Path(run_dir) / f"induce-{version}.json"


def write_induce_sidecar(run_dir: Path, stats: dict, version: str) -> Path:
    path = induce_path(run_dir, version)
    path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    return path

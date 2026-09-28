"""Planted-need checks: a self-contained synthetic cardset plus planted
comments with known true cards and decoys that fit none of them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import yaml

from atlas import paths
from atlas.cards.engine.cardset import CardSet, CardSetError, load_cardset


@dataclass(frozen=True)
class Planted:
    cardset: CardSet
    comments: list[dict]  # {comment_id, card_id, text}
    decoys: list[dict]  # {comment_id, text}


def load_planted(version: str = "v1") -> Planted:
    path = paths.CONFIGS / "cards" / f"planted.{version}.yaml"
    data = yaml.safe_load(path.read_bytes())
    return Planted(
        cardset=load_cardset("planted", version),
        comments=list(data.get("planted") or []),
        decoys=list(data.get("decoys") or []),
    )


def with_planted(cs: CardSet, planted: Planted) -> CardSet:
    """The base cardset plus the planted groups/cards. Raises on id collision."""
    pcs = planted.cardset
    group_clash = set(cs.groups) & set(pcs.groups)
    card_clash = set(cs.all_cards) & set(pcs.all_cards)
    if group_clash or card_clash:
        raise CardSetError(
            f"planted ids collide: groups={sorted(group_clash)} "
            f"cards={sorted(card_clash)}"
        )
    all_cards = {**cs.all_cards, **pcs.all_cards}
    cards = {cid: c for cid, c in all_cards.items() if c.status == "approved"}
    sha = hashlib.sha256(
        f"{cs.sha256}:{pcs.sha256}".encode()
    ).hexdigest()
    return CardSet(
        name=f"{cs.name}+{pcs.name}",
        version=f"{cs.version}+planted-{pcs.version}",
        groups={**cs.groups, **pcs.groups},
        cards=cards,
        all_cards=all_cards,
        sha256=sha,
    )


def planted_items(planted: Planted) -> list[dict]:
    items = [
        {
            "comment_id": c["comment_id"],
            "pain_sentence": c["text"],
            "sentences": [c["text"]],
        }
        for c in planted.comments
    ]
    items += [
        {
            "comment_id": d["comment_id"],
            "pain_sentence": d["text"],
            "sentences": [d["text"]],
        }
        for d in planted.decoys
    ]
    return items


def planted_score(assignments: list[dict], planted: Planted) -> dict:
    """Recovery share on planted comments, decoy false-assignment rate, and a
    per-need breakdown. Missing rows count as misses."""
    by_cid = {r["comment_id"]: r for r in assignments}
    per_need: dict[str, list[int]] = {}
    for c in planted.comments:
        got, total = per_need.setdefault(c["card_id"], [0, 0])
        hit = by_cid.get(c["comment_id"], {}).get("card_id") == c["card_id"]
        per_need[c["card_id"]] = [got + int(hit), total + 1]
    planted_ids = set(planted.cardset.all_cards)
    false = sum(
        1
        for d in planted.decoys
        if by_cid.get(d["comment_id"], {}).get("card_id") in planted_ids
    )
    n_planted = len(planted.comments)
    n_decoys = len(planted.decoys)
    return {
        "recovery": sum(v[0] for v in per_need.values()) / n_planted
        if n_planted
        else 0.0,
        "decoy_false_rate": false / n_decoys if n_decoys else 0.0,
        "per_need": {k: v[0] / v[1] for k, v in per_need.items()},
        "n_planted": n_planted,
        "n_decoys": n_decoys,
    }

"""Versioned need-card sets loaded from configs/cards/<name>.<version>.yaml.

YAML shape:

    taxonomy_version: t0
    groups:
      g01: {label: "Build and deploy pipelines"}
    cards:
      - {card_id: c0001, group_id: g01, statement: "...", status: approved,
         author: claude+hansel}

`status` is one of draft | approved | retired | merged_into:<card_id>. Only
approved cards are active. Extra top-level keys (planted, decoys) are ignored.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pyarrow as pa
import yaml

from atlas import contracts, paths

MAX_GROUPS = 254
MAX_CARDS_PER_GROUP = 254
STATUSES = ("draft", "approved", "retired")
MERGED_PREFIX = "merged_into:"


class CardSetError(ValueError):
    pass


@dataclass(frozen=True)
class Card:
    card_id: str
    group_id: str
    statement: str
    status: str
    author: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class CardSet:
    name: str
    version: str
    groups: dict[str, str]  # group_id -> label
    cards: dict[str, Card]  # active (approved) only, insertion order preserved
    all_cards: dict[str, Card]  # every card in the file
    sha256: str  # hex SHA-256 of the raw YAML bytes

    def resolve(self, card_id: str) -> str:
        """Follow merged_into:<id> chains to the final card id."""
        seen = set()
        cid = card_id
        while True:
            card = self.all_cards.get(cid)
            if card is None:
                raise CardSetError(f"unknown card_id {cid!r} (from {card_id!r})")
            if not card.status.startswith(MERGED_PREFIX):
                return cid
            if cid in seen:
                raise CardSetError(f"merged_into cycle at {cid!r}")
            seen.add(cid)
            cid = card.status[len(MERGED_PREFIX):]

    def try_resolve(self, card_id) -> str | None:
        """``resolve`` for boundaries that take raw assignment output:
        ``None`` for ids absent from the file, the resolved id otherwise."""
        if not isinstance(card_id, str) or card_id not in self.all_cards:
            return None
        return self.resolve(card_id)

    def cards_in(self, group_id: str) -> list[Card]:
        """Active cards in a group, in file order."""
        return [c for c in self.cards.values() if c.group_id == group_id]


def _validate(data: dict, version: str) -> None:
    if not isinstance(data, dict):
        raise CardSetError("cardset file is not a mapping")
    if data.get("taxonomy_version") != version:
        raise CardSetError(
            f"taxonomy_version is {data.get('taxonomy_version')!r}, expected {version!r}"
        )
    groups = data.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise CardSetError("groups must be a non-empty mapping")
    if len(groups) > MAX_GROUPS:
        raise CardSetError(f"{len(groups)} groups exceeds {MAX_GROUPS}")
    for gid, g in groups.items():
        if not isinstance(g, dict) or not str(g.get("label") or "").strip():
            raise CardSetError(f"group {gid!r} has no label")


def load_cardset(name: str, version: str) -> CardSet:
    path = paths.CONFIGS / "cards" / f"{name}.{version}.yaml"
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    _validate(data, version)
    groups = {gid: str(g["label"]) for gid, g in data["groups"].items()}
    all_cards: dict[str, Card] = {}
    for entry in data.get("cards") or []:
        card = Card(
            card_id=entry["card_id"],
            group_id=entry["group_id"],
            statement=entry["statement"],
            status=entry["status"],
            author=entry.get("author"),
            created_at=entry.get("created_at"),
        )
        if card.card_id in all_cards:
            raise CardSetError(f"duplicate card_id {card.card_id!r}")
        if card.group_id not in groups:
            raise CardSetError(f"card {card.card_id!r} in unknown group {card.group_id!r}")
        if card.status in STATUSES:
            pass
        elif card.status.startswith(MERGED_PREFIX):
            target = card.status[len(MERGED_PREFIX):]
            if not target:
                raise CardSetError(f"card {card.card_id!r} merges into nothing")
        else:
            raise CardSetError(f"card {card.card_id!r} has bad status {card.status!r}")
        all_cards[card.card_id] = card
    for card in all_cards.values():
        if card.status.startswith(MERGED_PREFIX):
            target = card.status[len(MERGED_PREFIX):]
            if target not in all_cards:
                raise CardSetError(
                    f"card {card.card_id!r} merges into unknown {target!r}"
                )
    active = {cid: c for cid, c in all_cards.items() if c.status == "approved"}
    counts: dict[str, int] = {}
    for c in active.values():
        counts[c.group_id] = counts.get(c.group_id, 0) + 1
        if counts[c.group_id] > MAX_CARDS_PER_GROUP:
            raise CardSetError(
                f"group {c.group_id!r} has over {MAX_CARDS_PER_GROUP} active cards"
            )
    return CardSet(
        name=name,
        version=version,
        groups=groups,
        cards=active,
        all_cards=all_cards,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def cards_table(cs: CardSet) -> pa.Table:
    """Every card in the file as contract CARDS rows."""
    rows = [
        {
            "card_id": c.card_id,
            "group_id": c.group_id,
            "group_label": cs.groups[c.group_id],
            "statement": c.statement,
            "taxonomy_version": cs.version,
            "status": c.status,
            "author": c.author,
            "created_at": c.created_at,
        }
        for c in cs.all_cards.values()
    ]
    return pa.Table.from_pylist(rows, schema=contracts.CARDS)

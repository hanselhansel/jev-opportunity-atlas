"""Task 11.2: cardset loading, validation, resolve, and the CARDS table."""

import pytest
import yaml

from atlas import contracts, paths
from atlas.cards.engine.cardset import (
    CardSetError,
    cards_table,
    load_cardset,
)


def _write(tmp_path, monkeypatch, data, name="bad", version="t9"):
    cards_dir = tmp_path / "configs" / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / f"{name}.{version}.yaml").write_text(
        yaml.safe_dump(data), encoding="utf-8"
    )
    monkeypatch.setattr(paths, "CONFIGS", tmp_path / "configs")


def _base(**over):
    data = {
        "taxonomy_version": "t9",
        "groups": {"g1": {"label": "Group one"}, "g2": {"label": "Group two"}},
        "cards": [
            {"card_id": "c1", "group_id": "g1", "statement": "Need one",
             "status": "approved"},
        ],
    }
    data.update(over)
    return data


def test_load_example():
    cs = load_cardset("example", "t0")
    assert cs.name == "example" and cs.version == "t0"
    assert set(cs.groups) == {"g01", "g02"}
    assert len(cs.sha256) == 64


def test_active_filtering_and_resolve():
    cs = load_cardset("example", "t0")
    assert "c0004" not in cs.cards  # draft
    assert "c0005" not in cs.cards  # merged
    assert "c0004" in cs.all_cards and "c0005" in cs.all_cards
    assert cs.resolve("c0005") == "c0003"
    assert cs.resolve("c0001") == "c0001"
    assert [c.card_id for c in cs.cards_in("g01")] == ["c0001", "c0002"]


def test_resolve_unknown_and_cycle(tmp_path, monkeypatch):
    cs = load_cardset("example", "t0")
    with pytest.raises(CardSetError):
        cs.resolve("nope")
    _write(tmp_path, monkeypatch, _base(cards=[
        {"card_id": "c1", "group_id": "g1", "statement": "a",
         "status": "merged_into:c2"},
        {"card_id": "c2", "group_id": "g1", "statement": "b",
         "status": "merged_into:c1"},
    ]))
    with pytest.raises(CardSetError):
        load_cardset("bad", "t9").resolve("c1")


def test_version_mismatch(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _base(taxonomy_version="other"))
    with pytest.raises(CardSetError):
        load_cardset("bad", "t9")


def test_duplicate_card_id(tmp_path, monkeypatch):
    card = {"card_id": "c1", "group_id": "g1", "statement": "a",
            "status": "approved"}
    _write(tmp_path, monkeypatch, _base(cards=[card, dict(card)]))
    with pytest.raises(CardSetError):
        load_cardset("bad", "t9")


def test_unknown_group_and_empty_label(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _base(cards=[
        {"card_id": "c1", "group_id": "gx", "statement": "a",
         "status": "approved"},
    ]))
    with pytest.raises(CardSetError):
        load_cardset("bad", "t9")
    _write(tmp_path, monkeypatch,
           _base(groups={"g1": {"label": "  "}}), name="bad2")
    with pytest.raises(CardSetError):
        load_cardset("bad2", "t9")


def test_bad_status_and_merge_target(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _base(cards=[
        {"card_id": "c1", "group_id": "g1", "statement": "a",
         "status": "bogus"},
    ]))
    with pytest.raises(CardSetError):
        load_cardset("bad", "t9")
    _write(tmp_path, monkeypatch, _base(cards=[
        {"card_id": "c1", "group_id": "g1", "statement": "a",
         "status": "merged_into:ghost"},
    ]), name="bad3")
    with pytest.raises(CardSetError):
        load_cardset("bad3", "t9")


def test_group_and_card_limits(tmp_path, monkeypatch):
    groups = {f"g{i:03d}": {"label": f"G{i}"} for i in range(255)}
    _write(tmp_path, monkeypatch, _base(groups=groups))
    with pytest.raises(CardSetError):
        load_cardset("bad", "t9")
    cards = [
        {"card_id": f"c{i:03d}", "group_id": "g1", "statement": f"s{i}",
         "status": "approved"}
        for i in range(255)
    ]
    _write(tmp_path, monkeypatch, _base(cards=cards), name="bad4")
    with pytest.raises(CardSetError):
        load_cardset("bad4", "t9")


def test_extra_top_level_keys_ignored(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _base(planted=[{"x": 1}], decoys=[{"y": 2}]))
    cs = load_cardset("bad", "t9")
    assert "c1" in cs.cards


def test_cards_table_matches_contract():
    table = cards_table(load_cardset("example", "t0"))
    assert table.schema.equals(contracts.CARDS)
    assert table.num_rows == 5
    row = {r["card_id"]: r for r in table.to_pylist()}["c0003"]
    assert row["group_label"] == "Back-office admin and money"
    assert row["taxonomy_version"] == "t0"

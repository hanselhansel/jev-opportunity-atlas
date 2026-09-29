"""Task 18.1: schema and coverage checks for configs/benchmark/cases.v1.yaml."""

import json
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "configs" / "benchmark" / "cases.v1.yaml"

YES_CATEGORIES = {
    "genuine_firsthand", "solved_past", "question_own_problem", "card_placement",
}
NO_CATEGORIES = {
    "question_no_problem", "general_opinion", "secondhand", "hypothetical",
    "pitch", "we_general", "meta_note", "one_line_reaction",
}
MIXED_CATEGORIES = {"sarcasm", "injected"}
CATEGORIES = YES_CATEGORIES | NO_CATEGORIES | MIXED_CATEGORIES
CASE_KEYS = {"id", "category", "text", "parent", "expected", "why"}
EXPECTED_KEYS = {
    "firsthand_problem", "account_type", "workaround", "paid", "switched",
    "resolution", "card",
}


def _load():
    return yaml.safe_load(CASES.read_text(encoding="utf-8"))


def _cases():
    return _load()["cases"]


def _choices(name, version, qid):
    path = ROOT / "configs" / "questions" / f"{name}.v{version}.json"
    return set(json.loads(path.read_text())["questions"][qid]["criteria"])


def _cards():
    data = yaml.safe_load((ROOT / "configs/cards/pilot.t1.yaml").read_text())
    return {
        c["card_id"]: c["group_id"]
        for c in data["cards"]
        if c["status"] == "approved"
    }


def test_header_and_size():
    data = _load()
    assert data["version"] == 1
    assert set(data["categories"]) == CATEGORIES
    assert 180 <= len(data["cases"]) <= 240


def test_ids_synthetic_and_unique():
    ids = [c["id"] for c in _cases()]
    assert all(isinstance(i, int) for i in ids)
    assert all(9_400_000_001 <= i < 9_500_000_000 for i in ids)
    assert len(ids) == len(set(ids))


def test_schema():
    accounts = _choices("screen", 1, "account_type")
    resolutions = _choices("facets", 2, "resolution")
    cards = set(_cards()) | {"none"}
    for c in _cases():
        assert set(c) <= CASE_KEYS, c["id"]
        assert {"id", "category", "text", "expected", "why"} <= set(c), c["id"]
        assert c["category"] in CATEGORIES, c["id"]
        assert isinstance(c["text"], str) and c["text"].strip(), c["id"]
        assert isinstance(c["why"], str) and c["why"].strip(), c["id"]
        assert "http" not in c["text"], c["id"]
        exp = c["expected"]
        assert set(exp) <= EXPECTED_KEYS, c["id"]
        assert exp["firsthand_problem"] in ("yes", "no"), c["id"]
        assert exp["account_type"] in accounts, c["id"]
        for facet in ("workaround", "paid", "switched"):
            if facet in exp:
                assert exp[facet] in ("yes", "no"), c["id"]
        if "resolution" in exp:
            assert exp["resolution"] in resolutions, c["id"]
        if "card" in exp:
            assert exp["card"] in cards, c["id"]


def test_category_counts():
    counts = Counter(c["category"] for c in _cases())
    for cat in CATEGORIES - {"card_placement"}:
        assert counts[cat] >= 12, cat


def test_card_placement_coverage():
    card_cases = [c for c in _cases() if "card" in c["expected"]]
    assert all(c["category"] == "card_placement" for c in card_cases)
    assert counts_ok(Counter(c["expected"]["card"] for c in card_cases))
    assert all(
        "card" in c["expected"]
        for c in _cases()
        if c["category"] == "card_placement"
    )


def counts_ok(per_card: Counter) -> bool:
    none = per_card.pop("none", 0)
    return none == 10 and len(per_card) == 20 and set(per_card.values()) == {3}


def test_expected_follows_category_rules():
    for c in _cases():
        exp = c["expected"]
        if c["category"] in YES_CATEGORIES:
            assert exp["firsthand_problem"] == "yes", c["id"]
        if c["category"] in NO_CATEGORIES:
            assert exp["firsthand_problem"] == "no", c["id"]
        if c["category"] == "solved_past":
            assert exp["resolution"] == "resolved", c["id"]
        if c["category"] == "question_own_problem":
            assert exp["account_type"] == "question_or_request", c["id"]
        if c["category"] == "pitch":
            assert exp["account_type"] == "product_pitch", c["id"]
        if c["category"] == "secondhand":
            assert exp["account_type"] == "secondhand_report", c["id"]
        if exp["firsthand_problem"] == "no":
            assert "card" not in exp, c["id"]
            assert exp["account_type"] != "firsthand_account", c["id"]


def test_mixed_categories_have_both_answers():
    for cat in MIXED_CATEGORIES:
        answers = {
            c["expected"]["firsthand_problem"]
            for c in _cases()
            if c["category"] == cat
        }
        assert answers == {"yes", "no"}, cat

"""The ``card_share`` table: weighted shares of firsthand problems per need
group and card, per population and half-year bucket, with intervals and
BH-adjusted p-values on the H2 - H1 difference.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.estimation.robust import benjamini_hochberg
from atlas.sitedata.build_card_share import _bh_adjust, card_share_rows
from atlas.sitedata.tables import SITE_TABLES
from tests.sitedata.world import CARDS, TV, build, build_world, read

QUALIFIER = "as classified by Jev; assignment audited"
LEVELS = ("group", "card")
POPULATIONS = ("screen_positive", "all_firsthand")
BUCKETS = ("all", "H1", "H2", "H2_minus_H1")


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def _rows(out) -> list[dict]:
    return read(out, "card_share")


def _items(world, phases=("pos",)):
    """Expected firsthand problems: facet rows in ``phases`` with a
    firsthand account_type, joined to the (cardset) assignment."""
    assigned = {
        r["comment_id"]: r
        for r in pq.read_table(
            paths_run_dir() / f"assignments-{TV}.parquet"
        ).to_pylist()
    }
    items = []
    for cid, f in world["facet"].items():
        if f["phase"] not in phases or world["account"][cid] != "firsthand_account":
            continue
        a = assigned.get(cid) or {}
        card = a.get("card_id")
        if (
            card in (None, "none")
            or card not in CARDS
            or (a.get("card_p") or 0.0) < 0.5
        ):
            card = None
        items.append(
            {
                "comment_id": cid,
                "weight": f["weight"],
                "period": world["period"][cid],
                "card": card,
            }
        )
    return items


def paths_run_dir():
    from atlas import paths

    return paths.run_dir("assign-syn")


def _share(items, key, value, period=None):
    sub = [r for r in items if period is None or _half(r["period"]) == period]
    num = sum(r["weight"] for r in sub if r[key] == value)
    den = sum(r["weight"] for r in sub)
    return num / den, sum(1 for r in sub if r[key] == value)


def _half(period):
    if period <= "P06":
        return "H1"
    if period <= "P12":
        return "H2"
    return None


def _card_groups():
    return {"c01": "g01", "c02": "g01", "c03": "g02", "c04": "g02"}


def test_table_schema_and_row_fields(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    got = pq.read_schema(out / "card_share.parquet")
    base = SITE_TABLES["card_share"]
    assert pa.schema(list(got)[: len(base)]).equals(base)
    assert got.names[len(base) :] == ["short_label"]
    rows = _rows(out)
    assert rows
    for r in rows:
        assert r["level"] in LEVELS
        assert r["population"] in POPULATIONS
        assert r["bucket"] in BUCKETS
        assert r["qualifier"] == QUALIFIER
        assert r["n_items"] >= 0 and r["n_authors"] >= 0
        if r["bucket"] != "H2_minus_H1":
            assert r["p_adj"] is None
    # Every cardset id appears, for every population and bucket.
    keys = {(r["population"], r["level"], r["id"], r["bucket"]) for r in rows}
    for pop in POPULATIONS:
        for c in CARDS:
            for b in BUCKETS:
                assert (pop, "card", c, b) in keys
        for g in ("g01", "g02"):
            for b in BUCKETS:
                assert (pop, "group", g, b) in keys


def test_card_share_matches_weighted_estimand(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    rows = {
        (r["population"], r["level"], r["id"], r["bucket"]): r
        for r in _rows(out)
    }
    group_of = _card_groups()
    for pop, phases in (
        ("screen_positive", ("pos",)),
        ("all_firsthand", ("pos", "neg")),
    ):
        items = _items(world, phases)
        for r in items:
            r["group"] = group_of.get(r["card"]) if r["card"] else None
        for level in LEVELS:
            for x in (CARDS if level == "card" else ("g01", "g02")):
                for b in ("all", "H1", "H2"):
                    period = None if b == "all" else b
                    exp, n = _share(items, level, x, period)
                    got = rows[(pop, level, x, b)]
                    assert got["share"] == pytest.approx(exp)
                    assert got["n_items"] == n
                    assert got["lo"] <= got["hi"]
                    if b == "all":
                        assert got["lo"] <= got["share"] <= got["hi"]
                h1, _ = _share(items, level, x, "H1")
                h2, _ = _share(items, level, x, "H2")
                got = rows[(pop, level, x, "H2_minus_H1")]
                assert got["share"] == pytest.approx(h2 - h1)


def test_shares_sum_to_at_most_one_per_level(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    rows = _rows(out)
    for pop in POPULATIONS:
        for level in LEVELS:
            for b in ("all", "H1", "H2"):
                total = sum(
                    r["share"]
                    for r in rows
                    if r["population"] == pop
                    and r["level"] == level
                    and r["bucket"] == b
                )
                assert total <= 1.0 + 1e-9
                # "none" assignments stay in the denominator, so < 1 here.
                assert total < 1.0


def test_all_firsthand_adds_the_neg_check_slice(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    rows = _rows(out)
    pos_n = {
        r["id"]: r["n_items"]
        for r in rows
        if r["population"] == "screen_positive"
        and r["bucket"] == "all"
        and r["level"] == "card"
    }
    all_n = {
        r["id"]: r["n_items"]
        for r in rows
        if r["population"] == "all_firsthand"
        and r["bucket"] == "all"
        and r["level"] == "card"
    }
    for x in CARDS:
        assert all_n[x] >= pos_n[x]
    assert any(all_n[x] > pos_n[x] for x in CARDS)


def test_p_adj_is_bh_adjusted_within_level_and_population(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    rows = _rows(out)
    for pop in POPULATIONS:
        for level in LEVELS:
            diff = [
                r
                for r in rows
                if r["population"] == pop
                and r["level"] == level
                and r["bucket"] == "H2_minus_H1"
            ]
            finite = [r["p_adj"] for r in diff if r["p_adj"] is not None]
            assert all(0.0 <= p <= 1.0 for p in finite)


def test_bh_adjust_matches_benjamini_hochberg_rejections():
    p = np.array([0.001, 0.01, 0.04, 0.20, 0.50, 0.90])
    adj = _bh_adjust(p)
    for q in (0.01, 0.05, 0.10):
        assert (adj <= q).tolist() == benjamini_hochberg(p, q).tolist()
    # Canonical BH example.
    adj2 = _bh_adjust(np.array([0.01, 0.02, 0.03, 0.04, 0.05]))
    assert adj2[4] == pytest.approx(0.05)


def _mini_ctx():
    """Two strata. c01's six items all sit on one thread; c02's six items are
    spread over six threads. All weights equal, so point shares match."""
    cs = SimpleNamespace(
        groups={"g01": "G one", "g02": "G two"},
        all_cards={
            "c01": SimpleNamespace(statement="need one", group_id="g01"),
            "c02": SimpleNamespace(statement="need two", group_id="g01"),
        },
        cards={
            "c01": SimpleNamespace(statement="need one", group_id="g01"),
            "c02": SimpleNamespace(statement="need two", group_id="g01"),
        },
    )
    facet, answers, comments, assign = {}, {}, {}, {}
    cid = 9_000_000_000
    base = 9_500_000_000

    def add(story, stratum, card=None):
        nonlocal cid
        cid += 1
        facet[cid] = {
            "phase": "pos",
            "stratum": stratum,
            "story_id": story,
            "weight": 1.0,
            "firsthand_p": 0.9,
        }
        answers[cid] = {"account_type": {"choice": "firsthand_account"}}
        comments[cid] = {"period": "P03", "author": f"u{cid % 7}"}
        if card:
            assign[cid] = {"card_id": card, "card_p": 0.9, "group_id": "g01"}

    for _ in range(6):
        add(base + 0, "s0", card="c01")
    for s in range(1, 7):
        add(base + s, "s1" if s % 2 else "s0", card="c02")
    for s in range(7, 13):
        for _ in range(2):
            add(base + s, "s1" if s % 2 else "s0")
    ctx = {
        "facet": facet,
        "answers": answers,
        "comments": comments,
        "assign": assign,
    }
    return ctx, cs


def test_card_with_one_thread_gets_a_wider_interval():
    ctx, cs = _mini_ctx()
    rows = card_share_rows(ctx, cs, n_boot=2000, seed=0)
    by = {
        (r["id"], r["bucket"]): r
        for r in rows
        if r["level"] == "card" and r["population"] == "screen_positive"
    }
    w1 = by[("c01", "all")]["hi"] - by[("c01", "all")]["lo"]
    w2 = by[("c02", "all")]["hi"] - by[("c02", "all")]["lo"]
    assert by[("c01", "all")]["share"] == pytest.approx(by[("c02", "all")]["share"])
    assert w1 > w2
    assert w1 > 0.2


def test_card_share_rows_skip_merged_cards():
    """A merged card keeps its record in the cardset but emits no rows."""
    active = {
        "c01": SimpleNamespace(statement="need one", group_id="g01"),
        "c02": SimpleNamespace(statement="need two", group_id="g01"),
    }
    cs = SimpleNamespace(
        groups={"g01": "G one"},
        cards=active,
        all_cards={
            **active,
            "c03": SimpleNamespace(statement="dup", group_id="g01"),
        },
    )
    ctx = {
        "facet": {},
        "answers": {},
        "comments": {},
        "assign": {},
    }
    rows = card_share_rows(ctx, cs, n_boot=10, seed=0)
    card_ids = {r["id"] for r in rows if r["level"] == "card"}
    assert card_ids == {"c01", "c02"}

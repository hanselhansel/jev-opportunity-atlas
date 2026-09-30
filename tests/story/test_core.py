"""Task 1 + 3: frame loading and the core story sections."""

import math

from tests.story import world


def _load(tmp_path, monkeypatch):
    w = world.build_world(tmp_path, monkeypatch)
    from atlas.story import frame

    df = frame.load_frame(
        w["sample"], world.FACETS_RUN, world.ASSIGN_RUN, w["snapshot"],
        cardset="syn", version=world.TV,
    )
    return w, df


def _core(tmp_path, monkeypatch, R=200):
    w, df = _load(tmp_path, monkeypatch)
    from atlas.story import core

    return w, core.build_core(
        df, w["snapshot"], screen_run=world.SCREEN_RUN, R=R, seed=0
    )


def test_load_frame_columns_and_population(tmp_path, monkeypatch):
    w, df = _load(tmp_path, monkeypatch)
    for col in (
        "comment_id", "story_id", "stratum", "phase", "wave", "weight",
        "period", "author", "account_type", "domain", "user_role", "card",
        "group", "card_p", "firsthand", "placed", "severity", "specificity",
    ):
        assert col in df.columns
    for q in (
        "workaround", "cost_time", "cost_money", "cost_reliability",
        "cost_customers", "paid", "switched", "tried_alternatives", "abandoned",
    ):
        assert f"f_{q}" in df.columns
    assert len(df) == len(w["pos"]) + len(w["neg"])
    neg = df[df.comment_id == w["neg"][0]].iloc[0]
    assert neg["phase"] == "neg"
    placed = df[df.placed]
    assert placed["firsthand"].all()
    assert placed["card"].notna().all()
    assert len(placed) < len(df[df.firsthand])


def test_shares_sum_leq_one(tmp_path, monkeypatch):
    _, core = _core(tmp_path, monkeypatch)
    groups = {g["id"]: g for g in core["groups"]}
    for key in ["share", "h1", "h2"]:
        total = sum(g[key]["est"] for g in groups.values() if g[key])
        assert 0 < total <= 1.0
    for q in ("Q1", "Q2", "Q3", "Q4"):
        total = sum(
            g["quarters"][q]["est"]
            for g in groups.values()
            if g["quarters"][q]
        )
        assert total <= 1.0 + 1e-9
    for p in (f"P{i:02d}" for i in range(1, 13)):
        total = sum(
            g["months"][p]["est"] for g in groups.values() if g["months"][p]
        )
        assert total <= 1.0 + 1e-9


def test_sparse_period_flagged(tmp_path, monkeypatch):
    _, core = _core(tmp_path, monkeypatch)
    g01 = next(g for g in core["groups"] if g["id"] == "g01")
    p12 = g01["months"]["P12"]
    assert p12["n"] == 10 and p12["sparse"] is True
    assert p12["est"] is not None


def test_domains_use_neg_rows(tmp_path, monkeypatch):
    w, df = _load(tmp_path, monkeypatch)
    from atlas.story import core

    core1 = core.build_core(df, w["snapshot"], R=200, seed=0)
    df2 = df.copy()
    flip = {"software_development": "health_medical",
            "health_medical": "infrastructure_ops",
            "infrastructure_ops": "software_development"}
    mask = df2["comment_id"].isin(w["neg"])
    df2.loc[mask, "domain"] = df2.loc[mask, "domain"].map(flip)
    core2 = core.build_core(df2, w["snapshot"], R=200, seed=0)
    d1 = {d["id"]: d for d in core1["domains"]}
    d2 = {d["id"]: d for d in core2["domains"]}
    assert any(
        not math.isclose(d1[k]["discussion"]["est"], d2[k]["discussion"]["est"])
        for k in d1
    )
    for k in d1:
        assert math.isclose(
            d1[k]["complaints"]["est"], d2[k]["complaints"]["est"]
        )


def test_change_same_replicates(tmp_path, monkeypatch):
    _, core = _core(tmp_path, monkeypatch)
    for g in core["groups"]:
        if g["h1"] and g["h2"]:
            assert math.isclose(
                g["change"]["est"], g["h2"]["est"] - g["h1"]["est"],
                abs_tol=1e-12,
            )
            assert 0.0 <= g["change"]["p_adj"] <= 1.0
    for c in core["cards"]:
        if c["h1"] and c["h2"]:
            assert math.isclose(
                c["change"]["est"], c["h2"]["est"] - c["h1"]["est"],
                abs_tol=1e-12,
            )
            assert c["change"]["shrunk"] is not None


def test_core_shape(tmp_path, monkeypatch):
    _, core = _core(tmp_path, monkeypatch)
    steps = {s["key"]: s["count"] for s in core["funnel"]["steps"]}
    assert list(steps) == ["all", "eligible", "screened", "firsthand", "placed"]
    assert steps["all"] == 3990000 and steps["eligible"] == 3680000
    assert steps["screened"] > 0
    assert 0 < steps["placed"] < steps["firsthand"] < steps["screened"]
    assert len(core["funnel"]["months"]) == 12
    assert core["unplaced"]["share"]["est"] > 0
    assert core["unplaced"]["domains"]
    gids = {g["id"] for g in core["groups"]}
    assert set(core["roles"]["by_group"]) == gids
    assert set(core["roles"]["known_share"]) == gids
    for c in core["cards"]:
        assert {"id", "group", "short", "statement", "share", "h1", "h2",
                "change", "quarters", "n_problems", "n_authors",
                "n_threads"} <= set(c)


def test_labels_cover_every_story_id(tmp_path, monkeypatch):
    _, core = _core(tmp_path, monkeypatch)
    labels = core["labels"]
    dom_ids = {d["id"] for d in core["domains"]}
    dom_ids |= set(core["unplaced"]["domains"])
    role_ids = set(core["unplaced"]["roles"])
    for by_role in core["roles"]["by_group"].values():
        role_ids |= set(by_role)
    assert dom_ids <= set(labels["domains"])
    assert role_ids <= set(labels["roles"])
    assert all(
        isinstance(v, str) and v for v in labels["domains"].values()
    )
    assert all(
        isinstance(v, str) and v for v in labels["roles"].values()
    )


def test_labels_cover_facets_choice_keys(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.inference.questions import load_question_set
    from atlas.story import core

    labels = core.load_story_labels()
    qs = load_question_set("facets", 2)
    assert set(labels["domains"]) == set(
        qs.questions["domain"]["criteria"]
    )
    assert set(labels["roles"]) == set(
        qs.questions["user_role"]["criteria"]
    )

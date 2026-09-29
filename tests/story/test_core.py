"""Task 1 + 3: frame loading and the core story sections."""

from tests.story import world


def test_load_frame_columns_and_population(tmp_path, monkeypatch):
    w = world.build_world(tmp_path, monkeypatch)
    from atlas.story import frame

    df = frame.load_frame(
        w["sample"], world.FACETS_RUN, world.ASSIGN_RUN, w["snapshot"],
        cardset="syn", version=world.TV,
    )
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

"""Task 2 + wiring: opportunity score — percentile components, presets with
renormalization over non-null parts, bootstrap rank quantiles, and the
``story data --with score`` section end to end."""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.cards.replies import UNSOLVED
from atlas.story import score
from tests.story import world
from tests.story.test_check import DATA_ARGS


def _card(cid, n=60, share=None, shrunk=None, paid=None, unsolved=None,
          severe=None, ratio=None, reliability=None, customers=None):
    c = {"id": cid, "n_problems": n,
         "share": {"est": share} if share is not None else None,
         "change": {"shrunk": shrunk}}
    if paid is not None:
        c["coping"] = {"commercial": {"est": paid}}
    c["unsolved"] = (
        {"unsolved": {"est": unsolved}, "author_solved": {"est": 0.1}}
        if unsolved is not None
        else None
    )
    if severe is not None:
        c["quality"] = {"severe3": {"est": severe}}
    if ratio is not None:
        c["builders"] = {"ratio": {"est": ratio}}
    if reliability is not None or customers is not None:
        c["costs"] = {
            "reliability": {"est": reliability},
            "customers": {"est": customers},
        }
    return c


def _story(cards):
    return {"cards": cards}


def test_null_component_renormalizes():
    cards = [
        _card("cA", share=0.1, shrunk=0.01, paid=0.4, severe=0.3),
        _card("cB", share=0.2, shrunk=0.02, paid=0.3, severe=0.2, unsolved=0.5),
        _card("cC", share=0.3, shrunk=0.03, paid=0.2, severe=0.4, unsolved=0.6),
        _card("cD", share=0.4, shrunk=0.04, paid=0.1, severe=0.1, unsolved=0.7),
    ]
    cards_score, presets = score.build_scores(_story(cards), reps={})
    comp = cards_score["cA"]["components"]
    assert comp["unsolved"] is None
    manual = [v for v in comp.values() if v is not None]
    assert score.weighted_score(comp, presets["balanced"]) == pytest.approx(
        sum(manual) / len(manual)
    )
    # and it is not the naive mean with unsolved counted as zero
    assert not np.isclose(
        score.weighted_score(comp, presets["balanced"]),
        sum(manual) / len(comp),
    )


def test_all_zero_weights_equal():
    comp = {"share": 0.8, "change": 0.2, "paid": None, "unsolved": 0.4}
    zero = {k: 0 for k in score.COMPONENTS}
    expect = (0.8 + 0.2 + 0.4) / 3
    assert score.weighted_score(comp, zero) == pytest.approx(expect)
    assert score.weighted_score(comp, {}) == pytest.approx(expect)
    ones = {k: 1 for k in score.COMPONENTS}
    assert score.weighted_score(comp, ones) == pytest.approx(expect)


def test_rank_quantiles_monotone():
    rng = np.random.default_rng(0)
    cards = [
        _card(
            f"c{i:02d}",
            share=0.05 + 0.02 * i,
            shrunk=-0.02 + 0.01 * i,
            paid=0.1 + 0.05 * i,
            severe=0.2 + 0.03 * i,
        )
        for i in range(6)
    ]
    reps = {}
    for i, c in enumerate(cards):
        reps[c["id"]] = {
            "share": 0.05 + 0.02 * i + rng.normal(0, 0.01, 64),
            "change": -0.02 + 0.01 * i + rng.normal(0, 0.02, 64),
            "paid": 0.1 + 0.05 * i + rng.normal(0, 0.03, 64),
            "severity3": 0.2 + 0.03 * i + rng.normal(0, 0.03, 64),
        }
    cards_score, _ = score.build_scores(_story(cards), reps)
    qs = cards_score["c00"]["rank_quantiles"]
    assert len(qs) == 20
    assert all(isinstance(q, int) and q >= 1 for q in qs)
    assert qs == sorted(qs)


def test_thin_card_not_scored():
    cards = [
        _card("thin", n=12, share=0.5, shrunk=0.1),
        _card("fat", n=80, share=0.2, shrunk=0.0),
    ]
    cards_score, _ = score.build_scores(_story(cards), reps={})
    assert all(v is None for v in cards_score["thin"]["components"].values())
    assert cards_score["thin"]["rank_quantiles"] == []
    assert cards_score["fat"]["components"]["share"] == pytest.approx(0.5)


def test_underbuilt_is_neg_log_ratio():
    cards = [
        _card("cA", share=0.1, shrunk=0.0, ratio=0.1),
        _card("cB", share=0.2, shrunk=0.0, ratio=10.0),
    ]
    cards_score, _ = score.build_scores(_story(cards), reps={})
    # ratio 0.1 -> -log(0.1) high -> higher percentile than ratio 10
    assert (
        cards_score["cA"]["components"]["launch_ratio"]
        > cards_score["cB"]["components"]["launch_ratio"]
    )


def test_presets_cover_all_components():
    _, presets = score.build_scores(_story([_card("cA")]), reps={})
    for name in ("balanced", "growth", "paid_pain", "underbuilt"):
        assert set(presets[name]) == set(score.COMPONENTS)
        assert all(v >= 0 for v in presets[name].values())
    assert presets["growth"]["change"] == 3
    assert presets["paid_pain"]["paid"] == 3
    assert presets["underbuilt"]["launch_ratio"] == 3


def test_story_data_with_score_end_to_end(tmp_path, monkeypatch):
    w = world.build_world(tmp_path, monkeypatch)
    from atlas import paths
    from atlas.story import frame

    fr = frame.load_frame(
        w["sample"], world.FACETS_RUN, world.ASSIGN_RUN, w["snapshot"],
        cardset="syn", version=world.TV,
    )
    c01_ids = fr[
        (fr["phase"] == "pos") & fr["firsthand"] & (fr["card"] == "c01")
    ]["comment_id"].tolist()[:35]
    assert len(c01_ids) >= 30

    run_dir = paths.run_dir(world.ASSIGN_RUN)
    replies_dir = run_dir / "replies"
    replies_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "comment_id": int(c),
                    "n_replies": 2,
                    "any_solution_named": False,
                    "solution_kinds": [],
                    "author_says_solved": "still_unsolved" if i % 4 else "solved",
                    "unsolved": True,
                    "solved_p": 0.0,
                }
                for i, c in enumerate(c01_ids)
            ],
            schema=UNSOLVED,
        ),
        replies_dir / "unsolved_by_problem.parquet",
    )
    (run_dir / f"merge-{world.TV}.json").write_text(
        json.dumps(
            {
                "scored": [
                    {"card_a": "c01", "card_b": "c02", "score": 1, "expected": 1.5},
                    {"card_a": "c01", "card_b": "c03", "score": 1, "expected": 1.5},
                    {"card_a": "c02", "card_b": "c03", "score": 1, "expected": 1.5},
                    {"card_a": "c01", "card_b": "c04", "score": 0, "expected": 0.5},
                ]
            }
        )
    )

    out = tmp_path / "story.json"
    from atlas.story import check, cli

    cli.main(["story", "data", "--out", str(out), *DATA_ARGS, "--with", "score"])
    doc = json.loads(out.read_text())

    cards = {c["id"]: c for c in doc["cards"]}
    assert cards["c01"]["unsolved"]["unsolved"]["est"] == pytest.approx(1.0)
    w_by_id = dict(zip(fr["comment_id"], fr["weight"]))
    want_solved = sum(
        w_by_id[int(c)] for i, c in enumerate(c01_ids) if i % 4 == 0
    ) / sum(w_by_id[int(c)] for c in c01_ids)
    assert cards["c01"]["unsolved"]["author_solved"]["est"] == pytest.approx(
        want_solved
    )
    for cid in ("c02", "c03", "c04"):
        assert cards[cid]["unsolved"] is None
    # c01 has replies data but only 49 problems, so it stays out of the
    # 50-problem scoring pool entirely.
    comps = cards["c01"]["score"]["components"]
    assert set(comps) == set(score.COMPONENTS)
    assert all(v is None for v in comps.values())
    for cid in ("c02", "c03"):
        c2 = cards[cid]["score"]["components"]
        assert c2["share"] is not None and c2["unsolved"] is None
        assert len(cards[cid]["score"]["rank_quantiles"]) == 20
    thin = cards["c04"]["score"]
    assert all(v is None for v in thin["components"].values())
    assert set(doc["score_presets"]) == {"balanced", "growth", "paid_pain", "underbuilt"}
    assert doc["bundles"] and set(doc["bundles"][0]["cards"]) == {"c01", "c02", "c03"}
    assert doc["bundles"][0]["persistence"] == 1.0
    assert {tuple(sorted((e["a"], e["b"]))) for e in doc["edges"]} == {
        ("c01", "c02"), ("c01", "c03"), ("c02", "c03"),
    }
    assert check.check_story(out) == []

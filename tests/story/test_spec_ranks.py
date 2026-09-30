"""Task 4: specification ranks — a card's rank under alternative rules."""

from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.story import spec_ranks

BASE, STORY = 9_000_000_000, 9_500_000_000
TV = "t9"
DOMINANT = [f"c{i:02d}" for i in range(1, 22)]  # c01..c21
FILLER = ["c22", "c23", "c24"]
STAR = "c25"


def _row(i, card, w=1.0, thread=None, author=None, card_p=0.9):
    return {
        "comment_id": BASE + i,
        "story_id": thread if thread is not None else STORY + i,
        "stratum": "s1",
        "phase": "pos",
        "firsthand": True,
        "card": card,
        "weight": w,
        "author": author if author is not None else f"u{i}",
        "card_p": card_p,
    }


def _world():
    rows = []
    i = 0
    for k, card in enumerate(DOMINANT):
        # 12 problems, all one author in one thread, high confidence
        for _ in range(12):
            rows.append(
                _row(i, card, w=1.0, thread=STORY + k,
                     author=f"one-{card}")
            )
            i += 1
    for card in FILLER:
        rows.append(_row(i, card, w=1.0))
        i += 1
    # c25: many distinct authors, one thread, low card_p, small weights
    for a in range(25):
        rows.append(
            _row(i, STAR, w=0.4, thread=STORY + 9999,
                 author=f"star-{a}", card_p=0.6)
        )
        i += 1
    return rows


def _para_run(root, run_id, cards, per_card):
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    rows = []
    cid = BASE + 5000
    for card in cards:
        for _ in range(per_card):
            rows.append(
                {
                    "run_id": run_id,
                    "comment_id": cid,
                    "taxonomy_version": TV,
                    "group_id": "g01",
                    "group_p": 0.9,
                    "group_confidence": 0.9,
                    "card_id": card,
                    "card_p": 0.9,
                    "card_confidence": 0.9,
                    "verified_p": None,
                }
            )
            cid += 1
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / f"assignments-{TV}.parquet",
    )


def _cardset(cards):
    return SimpleNamespace(
        all_cards={c: SimpleNamespace(group_id="g01") for c in cards},
        cards={c: SimpleNamespace(group_id="g01") for c in cards},
        version=TV,
        try_resolve=lambda c: c,
    )


def test_spec_ranks_union_top20(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    cards = DOMINANT + FILLER + [STAR]
    df = pd.DataFrame(_world())
    df.attrs["cardset"] = _cardset(cards)
    _para_run(tmp_path, "robust-assign-para1", DOMINANT, 5)
    _para_run(tmp_path, "robust-assign-para2", DOMINANT[:20], 5)
    out = spec_ranks.spec_ranks(
        df, {"para1": "robust-assign-para1", "para2": "robust-assign-para2"}
    )
    by_card = {r["card"]: r for r in out}
    # c25 is top-20 only under one_per_author; it must still appear
    assert STAR in by_card
    star = by_card[STAR]
    assert star["main_rank"] == 22  # 21 dominant cards have more weight
    assert star["alt_ranks"]["one_per_author"] == 1
    assert star["alt_ranks"]["one_per_thread"] > 20
    assert star["alt_ranks"]["card_p_0.7"] > 20
    assert star["alt_ranks"]["para1"] > 20
    assert set(star["alt_ranks"]) == {
        "card_p_0.7", "one_per_thread", "one_per_author", "para1", "para2"
    }
    c01 = by_card["c01"]
    assert c01["main_rank"] == 1
    assert c01["alt_ranks"]["card_p_0.7"] == 1


def test_spec_ranks_missing_para_run(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    df = pd.DataFrame(_world())
    df.attrs["cardset"] = _cardset(DOMINANT + FILLER + [STAR])
    out = spec_ranks.spec_ranks(
        df, {"para1": "robust-assign-para1", "para2": None}
    )
    for r in out:
        assert set(r["alt_ranks"]) == {
            "card_p_0.7", "one_per_thread", "one_per_author"
        }


def test_with_signals_end_to_end(tmp_path, monkeypatch):
    """`story data --with signals` merges S2 keys into cards + spec_ranks."""
    import json

    from tests.story import test_check, world

    world.build_world(tmp_path, monkeypatch)
    from atlas.story import cli

    out = tmp_path / "story.json"
    cli.main(["story", "data", "--out", str(out), *test_check.DATA_ARGS])
    cli.main(
        [
            "story", "data", "--out", str(out), *test_check.DATA_ARGS,
            "--only-with", "--with", "signals",
        ]
    )
    doc = json.loads(out.read_text())
    for c in doc["cards"]:
        for key in ("coping", "costs", "quality", "breadth",
                    "concentration"):
            assert key in c, (c["id"], key)
        assert set(c["coping"]) == {
            "paid", "switched", "abandoned", "workaround", "commercial"
        }
    assert isinstance(doc["spec_ranks"], list)
    assert doc["spec_ranks"]
    for r in doc["spec_ranks"]:
        assert {"card", "main_rank", "alt_ranks"} <= set(r)

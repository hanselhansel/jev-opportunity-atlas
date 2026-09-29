"""S3 amendment A1: ``_complaint_reps`` must use the master-plan population,
``phase == "pos"`` and ``firsthand`` — a heavy firsthand ``neg`` row assigned
to a card must not change that card's complaint share."""

from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from tests.story import world


def _args():
    return SimpleNamespace(
        snapshot=world.SNAPSHOT,
        facet_sample=world.SAMPLE,
        facets_run=world.FACETS_RUN,
        assign_run=world.ASSIGN_RUN,
        cardset="syn",
        version=world.TV,
    )


def _assign_neg_firsthand_to_c01():
    """Point a heavy neg-phase firsthand row at c01 inside the assign run."""
    table_path = paths.run_dir(world.ASSIGN_RUN) / f"assignments-{world.TV}.parquet"
    rows = pq.read_table(table_path).to_pylist()
    rows.append(
        {
            "run_id": world.ASSIGN_RUN,
            "comment_id": world.BASE + 900,  # neg phase, firsthand_account, weight 3.0
            "taxonomy_version": world.TV,
            "group_id": "g01",
            "group_p": 0.9,
            "group_confidence": 0.9,
            "card_id": "c01",
            "card_p": 0.9,
            "card_confidence": 0.9,
            "verified_p": 0.9,
        }
    )
    pq.write_table(pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS), table_path)


def test_neg_firsthand_row_does_not_move_card_share(tmp_path, monkeypatch):
    w = world.build_world(tmp_path, monkeypatch)
    _assign_neg_firsthand_to_c01()
    from atlas.builders import cli as builders_cli

    got = builders_cli._complaint_reps(_args(), ["c01", "c02"])

    # Expected share: weighted firsthand pos rows only (the master population).
    from atlas.story import frame

    fr = frame.load_frame(
        w["sample"], world.FACETS_RUN, world.ASSIGN_RUN, w["snapshot"],
        cardset="syn", version=world.TV,
    )
    fh = fr[(fr["phase"] == "pos") & fr["firsthand"]]
    for card in ("c01", "c02"):
        want = (
            fh.loc[fh["card"] == card, "weight"].sum() / fh["weight"].sum()
        )
        assert got[card]["est"] == pytest.approx(want, abs=1e-9)


def test_world_has_heavy_neg_firsthand_row(tmp_path, monkeypatch):
    """Guard the trap itself: the synthetic world really does carry the heavy
    neg firsthand rows this fix excludes."""
    w = world.build_world(tmp_path, monkeypatch)
    from atlas.story import frame

    fr = frame.load_frame(
        w["sample"], world.FACETS_RUN, world.ASSIGN_RUN, w["snapshot"],
        cardset="syn", version=world.TV,
    )
    heavy = fr[(fr["phase"] == "neg") & fr["firsthand"]]
    assert len(heavy) >= 1
    assert heavy["weight"].max() > fr[fr["phase"] == "pos"]["weight"].max()

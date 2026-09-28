import pytest

from atlas.sources.items import load_items
from atlas.sources.snapshot import build
from tests.sources.conftest import B, S


@pytest.fixture
def built_snapshot(raw_snapshot):
    cfg, root = raw_snapshot
    build(cfg, root, fetch_context_fn=None)
    return root / "data" / "snapshots" / "test-snap"


def test_load_items_parents_and_order(built_snapshot):
    sdir = built_snapshot
    out = load_items(sdir, [S + 3, S + 2, S + 8])
    assert [r["comment_id"] for r in out] == [S + 3, S + 2, S + 8]

    k3, k2, k8 = out
    # k3's parent is the scanned comment k2
    assert k3["parent"] == (
        "Synthetic comment about backup tooling that I run every night."
    )
    assert k3["comment"] == (
        "Synthetic reply noting that nightly restores worked in the drill."
    )
    assert k3["thread_type"] == "ask_hn"
    # k2's parent is the story; its text_norm is the story body
    assert k2["parent"] == "Synthetic story body about backup tooling choices."
    assert k2["story_title"] == "Ask HN: Synthetic question about backups?"
    # k8's parent lives only in context.parquet
    assert k8["parent"] == (
        "Synthetic context comment text outside the scanned range."
    )
    assert k8["story_title"] == "Synthetic old root story"
    assert k8["thread_type"] == "story"
    for r in out:
        assert isinstance(r["sentences"], list) and r["sentences"]
        assert len(r["text_sha256"]) == 64


def test_load_items_unknown_id_raises(built_snapshot):
    with pytest.raises(KeyError):
        load_items(built_snapshot, [B + 777])

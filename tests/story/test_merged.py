"""S8e review decision: n136 is a duplicate of n014 and merges into it.

The merged card keeps its cardset row with ``status: merged_into:n014``;
every consumer of assignment output resolves it to n014 — the frame, the
emitted story cards list, and the merge-score edges and bundles.
"""

import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from tests.story import world

REPO = Path(__file__).resolve().parents[2]
T3 = "t3"
N136_ROWS = 5
N014_ROWS = 7


def _t3_world(tmp_path, monkeypatch):
    """The synthetic world plus the real t3 cardset and a t3 assignments
    file that places firsthand problems on n136 and n014."""
    w = world.build_world(tmp_path, monkeypatch)
    cards_dir = paths.CONFIGS / "cards"
    for name in ("main.t3.yaml", "main.t3.labels.yaml"):
        shutil.copy(REPO / "configs" / "cards" / name, cards_dir / name)
    fh = sorted(w["firsthand"])
    rows = [
        {
            "run_id": world.ASSIGN_RUN,
            "comment_id": cid,
            "taxonomy_version": T3,
            "group_id": group,
            "group_p": 0.9,
            "group_confidence": 0.9,
            "card_id": card,
            "card_p": card_p,
            "card_confidence": 0.9,
            "verified_p": 0.9,
        }
        for cid, group, card, card_p in (
            [(c, "g01", "n136", 0.9) for c in fh[:N136_ROWS]]
            + [
                (c, "g02", "n014", 0.9)
                for c in fh[N136_ROWS:N136_ROWS + N014_ROWS]
            ]
            # below the counting cutoff: never lands on n014
            + [(fh[N136_ROWS + N014_ROWS], "g02", "n014", 0.3)]
            + [(fh[N136_ROWS + N014_ROWS + 1], "none", None, None)]
        )
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        paths.run_dir(world.ASSIGN_RUN) / f"assignments-{T3}.parquet",
    )
    return w


def _t3_frame(tmp_path, monkeypatch):
    from atlas.story import frame

    w = _t3_world(tmp_path, monkeypatch)
    return w, frame.load_frame(
        w["sample"],
        world.FACETS_RUN,
        world.ASSIGN_RUN,
        w["snapshot"],
        cardset="main",
        version=T3,
    )


def test_merged_card_resolves_in_frame(tmp_path, monkeypatch):
    """A synthetic assignment on n136 lands on n014 with the frame."""
    w, df = _t3_frame(tmp_path, monkeypatch)
    cs = df.attrs["cardset"]
    assert cs.resolve("n136") == "n014"
    merged = df[df["comment_id"].isin(sorted(w["firsthand"])[:N136_ROWS])]
    assert (merged["card"] == "n014").all()
    # n014 lives in g02, so merged problems move groups with it
    assert (merged["group"] == "g02").all()
    assert "n136" not in set(df["card"].dropna())


def test_merged_card_not_emitted(tmp_path, monkeypatch):
    """story cards carry no n136 row; n014 counts the merged problems."""
    w, df = _t3_frame(tmp_path, monkeypatch)
    from atlas.story import core

    out = core.build_core(df, w["snapshot"], R=100, seed=0)
    ids = [c["id"] for c in out["cards"]]
    assert "n136" not in ids
    n014 = next(c for c in out["cards"] if c["id"] == "n014")
    assert n014["n_problems"] == N136_ROWS + N014_ROWS
    for g in out["groups"]:
        assert "n136" not in g["cards"]


def test_bundle_edges_skip_self_pairs_after_merge():
    """Pairs whose ends resolve to the same card drop; the rest map
    through resolve, keeping the higher score on duplicate pairs."""
    from atlas.story import bundles

    merge_json = {
        "scored": [
            {"card_a": "n136", "card_b": "n014", "expected": 1.9},
            {"card_a": "n136", "card_b": "n050", "expected": 1.5},
            {"card_a": "n014", "card_b": "n050", "expected": 1.3},
            {"card_a": "n014", "card_b": "n051", "expected": 1.2},
        ]
    }
    story = {
        "cards": [
            {"id": c, "group": "g01", "share": {"est": 0.1}, "n_problems": 60}
            for c in ("n014", "n050", "n051")
        ]
    }
    _, edges = bundles.build_bundles(
        merge_json, story, resolve=lambda c: {"n136": "n014"}.get(c, c)
    )
    pairs = {(e["a"], e["b"]): e["score"] for e in edges}
    assert all(a != b for a, b in pairs)
    assert pairs == {("n014", "n050"): 1.5, ("n014", "n051"): 1.2}

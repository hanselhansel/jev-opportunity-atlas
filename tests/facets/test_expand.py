"""L27: second-wave expansion of the phase-2 facet sample.

Within a stratum an SRSWOR of n followed by an SRSWOR of m from the
remaining units is an SRSWOR of n+m, so the expanded sample keeps every
base row, tops each positive stratum up to the new allocate_capped target,
and recomputes p2 = (n_old_h + m_h) / N_h and weight = w1 / p2.
"""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.facets import expand, phase2
from tests.facets.test_phase2 import A, B, C, _write_screen_table
from tests.pilot.test_support import SNAPSHOT_ID, pilot_repo  # noqa: F401

_CUTOFF = 0.7


def _base_sample(n_pos=20, n_neg=6, seed=7, sample_id="fac-x"):
    """Screen fixture: A 40 pos w10 + 10 neg, B 20 pos w5 + 30 neg,
    C 15 pos w4. Base draw n_pos=20 -> A 14, B 4, C 2."""
    _write_screen_table()
    return phase2.draw_phase2(
        "scr-1",
        sample_id,
        n_pos=n_pos,
        n_neg=n_neg,
        cutoff=_CUTOFF,
        seed=seed,
        snapshot_id=SNAPSHOT_ID,
    )


def _pos(rows, stratum=None):
    return [
        r
        for r in rows
        if r["phase"] == "pos" and (stratum is None or r["stratum"] == stratum)
    ]


def test_expand_phase2_keeps_base_and_adds_wave2(pilot_repo):  # noqa: F811
    base = _base_sample()
    tbl = expand.expand_phase2(
        "scr-1", "fac-x", "fac-y", n_pos=40, seed=11
    )
    rows = tbl.to_pylist()
    base_ids = set(base.column("comment_id").to_pylist())
    assert base_ids <= set(tbl.column("comment_id").to_pylist())
    assert tbl.schema.field("wave").type == pa.int8()

    pos = _pos(rows)
    # wsum 400:100:60 of 40 -> A 29 (28.6), B 7 (7.1), C 4 (4.3)
    assert sum(r["stratum"] == A for r in pos) == 29
    assert sum(r["stratum"] == B for r in pos) == 7
    assert sum(r["stratum"] == C for r in pos) == 4
    wave1 = {r["comment_id"] for r in pos if r["wave"] == 1}
    wave2 = [r for r in pos if r["wave"] == 2]
    assert wave1 == {
        r["comment_id"] for r in base.to_pylist() if r["phase"] == "pos"
    }
    assert len(wave2) == 20
    for r in wave2:
        assert r["comment_id"] not in base_ids
        assert r["firsthand_p"] >= _CUTOFF

    meta = json.loads((paths.SAMPLES / "fac-y.json").read_text())
    assert meta["base_sample_id"] == "fac-x"
    assert meta["seed"] == 11
    assert meta["n_pos_target"] == 40
    assert meta["added"] == {"pos": 20, "neg": 0}
    assert meta["n_pos"] == 40
    assert meta["n_neg"] == 6
    assert meta["snapshot_id"] == SNAPSHOT_ID
    assert "SRSWOR" in meta["design"]


def test_expand_phase2_neg_rows_copied_unchanged(pilot_repo):  # noqa: F811
    base = _base_sample()
    tbl = expand.expand_phase2(
        "scr-1", "fac-x", "fac-y", n_pos=40, seed=11
    )
    base_neg = {
        r["comment_id"]: r
        for r in base.to_pylist()
        if r["phase"] == "neg"
    }
    neg = [r for r in tbl.to_pylist() if r["phase"] == "neg"]
    assert {r["comment_id"] for r in neg} == set(base_neg)
    for r in neg:
        b = base_neg[r["comment_id"]]
        assert r["p2"] == b["p2"]
        assert r["weight"] == b["weight"]
        assert r["w1"] == b["w1"]
        assert r["wave"] == 1


def test_expand_phase2_weights_sum_to_stratum_wsum(pilot_repo):  # noqa: F811
    _base_sample()
    tbl = expand.expand_phase2(
        "scr-1", "fac-x", "fac-y", n_pos=40, seed=11
    )
    screen = pq.read_table(
        paths.run_dir("scr-1") / "screen_by_comment.parquet"
    ).to_pylist()
    rows = tbl.to_pylist()
    for h in (A, B, C):
        frame = [
            r
            for r in screen
            if r["stratum"] == h and r["firsthand_p"] >= _CUTOFF
        ]
        sel = _pos(rows, h)
        # The stratum's selected positives reweight to its phase-1
        # weighted positive count.
        assert sum(r["weight"] for r in sel) == pytest.approx(
            sum(r["weight"] for r in frame), rel=1e-9
        )
        # One p2 per stratum: (n_old + m) / N on every selected row.
        for r in sel:
            assert r["p2"] == pytest.approx(len(sel) / len(frame))
            assert r["weight"] == pytest.approx(r["w1"] / r["p2"])


def test_expand_phase2_seed_determinism(pilot_repo):  # noqa: F811
    _base_sample()
    t1 = expand.expand_phase2("scr-1", "fac-x", "fac-a", n_pos=40, seed=11)
    t2 = expand.expand_phase2("scr-1", "fac-x", "fac-b", n_pos=40, seed=11)
    t3 = expand.expand_phase2("scr-1", "fac-x", "fac-c", n_pos=40, seed=12)
    assert t1.equals(t2)
    ids = lambda t: sorted(t.column("comment_id").to_pylist())
    assert ids(t1) != ids(t3)


def test_expand_phase2_smaller_target_adds_nothing(pilot_repo):  # noqa: F811
    base = _base_sample()
    tbl = expand.expand_phase2(
        "scr-1", "fac-x", "fac-y", n_pos=10, seed=11
    )
    assert sorted(tbl.column("comment_id").to_pylist()) == sorted(
        base.column("comment_id").to_pylist()
    )
    assert {r["wave"] for r in tbl.to_pylist()} == {1}
    meta = json.loads((paths.SAMPLES / "fac-y.json").read_text())
    assert meta["added"] == {"pos": 0, "neg": 0}


@pytest.mark.parametrize("n_pos", [20, 21, 40, 60, 75, 200])
def test_expand_phase2_never_shrinks_stratum(pilot_repo, n_pos):  # noqa: F811
    base = _base_sample()
    tbl = expand.expand_phase2(
        "scr-1", "fac-x", "fac-y", n_pos=n_pos, seed=11
    )
    rows = tbl.to_pylist()
    base_pos = _pos(base.to_pylist())
    new_pos = _pos(rows)
    assert {r["comment_id"] for r in base_pos} <= {
        r["comment_id"] for r in new_pos
    }
    sizes = {A: 40, B: 20, C: 15}
    for h in (A, B, C):
        n_old = sum(r["stratum"] == h for r in base_pos)
        n_new = sum(r["stratum"] == h for r in new_pos)
        assert n_old <= n_new <= sizes[h]


def test_expand_phase2_wrong_screen_run_refused(pilot_repo):  # noqa: F811
    _base_sample()
    with pytest.raises(ValueError, match="screen run"):
        expand.expand_phase2(
            "other-run", "fac-x", "fac-y", n_pos=40, seed=11
        )


# --- Task 27.2 tests (CLI, run resume pin) are added with that task ---

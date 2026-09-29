"""L22 22.2: two-phase facet sample and chunked, rate-limited run."""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
from atlas.facets import phase2
from atlas.inference import ratelimit
from atlas.screen.unpack import SCREEN_BY_COMMENT
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)
from tests.screen.support import FakeClock

A, B, C = "pain|L1|H1|ask", "nopain|L0|H2|story", "pain|L2|H1|show"


def _row(cid, stratum, half, weight, p, story=9_000_100_000):
    return {
        "comment_id": cid,
        "story_id": story,
        "stratum": stratum,
        "weight": weight,
        "half": half,
        "firsthand_p": p,
        "packed_id": 9_500_000_000,
        "slot": "c1",
        "model_returned": "jev-1.13.0",
        "request_id": "req-1",
    }


def _write_screen_table(run_id="scr-1"):
    """A: 40 pos w10 + 10 neg w10; B: 20 pos w5 + 30 neg w5; C: 15 pos w4."""
    rows = []
    cid = 9_100_000_000
    for stratum, pos_n, neg_n, w in ((A, 40, 10, 10.0), (B, 20, 30, 5.0), (C, 15, 0, 4.0)):
        for _ in range(pos_n):
            rows.append(_row(cid, stratum, "explore", w, 0.9))
            cid += 1
        for _ in range(neg_n):
            rows.append(_row(cid, stratum, "confirm", w, 0.2))
            cid += 1
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=SCREEN_BY_COMMENT),
        run_dir / "screen_by_comment.parquet",
    )
    return rows


def test_draw_phase2_allocation_and_weights(pilot_repo):  # noqa: F811
    _write_screen_table()
    tbl = phase2.draw_phase2(
        "scr-1",
        "fac-x",
        n_pos=20,
        n_neg=6,
        cutoff=0.7,
        seed=7,
        snapshot_id=SNAPSHOT_ID,
    )
    rows = tbl.to_pylist()
    pos = [r for r in rows if r["phase"] == "pos"]
    neg = [r for r in rows if r["phase"] == "neg"]
    # n2_h proportional to the stratum's phase-1 weighted count:
    # pos wsum 400:100:60 -> 14, 4, 2; neg wsum 100:150 -> 2, 4.
    assert {r["stratum"] for r in pos} == {A, B, C}
    assert sum(r["stratum"] == A for r in pos) == 14
    assert sum(r["stratum"] == B for r in pos) == 4
    assert sum(r["stratum"] == C for r in pos) == 2
    assert sum(r["stratum"] == A for r in neg) == 2
    assert sum(r["stratum"] == B for r in neg) == 4
    for r in rows:
        assert r["phase"] in ("pos", "neg")
        assert r["w1"] > 0
        assert 0 < r["p2"] <= 1
        assert r["weight"] == pytest.approx(r["w1"] / r["p2"])
        if r["phase"] == "pos":
            assert r["firsthand_p"] >= 0.7
        else:
            assert r["firsthand_p"] < 0.7

    meta = json.loads((paths.SAMPLES / "fac-x.json").read_text())
    assert meta["seed"] == 7
    assert meta["parent_run"] == "scr-1"
    assert meta["cutoff"] == 0.7
    assert meta["n_pos"] == 20
    assert meta["n_neg"] == 6
    assert meta["snapshot_id"] == SNAPSHOT_ID
    assert "w1/p2" in meta["design"]


def test_draw_phase2_seed_determinism(pilot_repo):  # noqa: F811
    _write_screen_table()
    t1 = phase2.draw_phase2(
        "scr-1", "fac-a", n_pos=20, n_neg=6, seed=7, snapshot_id=SNAPSHOT_ID
    )
    t2 = phase2.draw_phase2(
        "scr-1", "fac-b", n_pos=20, n_neg=6, seed=7, snapshot_id=SNAPSHOT_ID
    )
    t3 = phase2.draw_phase2(
        "scr-1", "fac-c", n_pos=20, n_neg=6, seed=8, snapshot_id=SNAPSHOT_ID
    )
    ids = lambda t: sorted(t.column("comment_id").to_pylist())
    assert ids(t1) == ids(t2)
    assert ids(t1) != ids(t3)


def test_allocate_capped_caps_stratum_and_redistributes():
    """A share above the stratum size caps it; the shortfall moves to the
    remaining open strata instead of being dropped."""
    wsum = {A: 400.0, B: 100.0, C: 60.0}
    sizes = {A: 40, B: 100, C: 100}
    # n=60 uncapped shares 42.9:10.7:6.4; A caps at 40, B:C split the
    # remaining 20 proportional to 100:60 -> 12.5, 7.5 -> 12 and 8 (half-even
    # rounding). A single min(len, share) pass would give B 11, C 6 (total 57).
    alloc = phase2.allocate_capped(wsum, sizes, 60)
    assert alloc[A] == 40
    assert alloc[B] == 12
    assert alloc[C] == 8
    assert abs(sum(alloc.values()) - 60) <= len(sizes)


def _reference_draw(t, *, n_pos, n_neg, cutoff, seed):
    """Inline copy of the main session's facets_phase2.py draw() core:
    proportional-to-weighted-count allocation capped at stratum size with the
    capped shortfall redistributed to open strata, then per-stratum SRSWOR."""
    rng = np.random.default_rng(seed)
    out = []
    for kind, n_total, keep in (
        ("pos", n_pos, lambda p: p >= cutoff),
        ("neg", n_neg, lambda p: p < cutoff),
    ):
        rows = [r for r in t if keep(r["firsthand_p"])]
        by = {}
        for r in rows:
            by.setdefault(r["stratum"], []).append(r)
        wsum = {h: sum(r["weight"] for r in rs) for h, rs in by.items()}
        alloc, open_h, left = {}, set(by), n_total
        while left > 0 and open_h:
            tot = sum(wsum[h] for h in open_h)
            share = {h: left * wsum[h] / tot for h in open_h}
            capped = {
                h for h in open_h if alloc.get(h, 0) + share[h] >= len(by[h])
            }
            if capped:
                for h in capped:
                    left -= len(by[h]) - alloc.get(h, 0)
                    alloc[h] = len(by[h])
                open_h -= capped
                continue
            for h in open_h:
                alloc[h] = alloc.get(h, 0) + share[h]
            left = 0
        alloc = {h: max(1, round(a)) for h, a in alloc.items()}
        for h in sorted(by):
            rs = sorted(by[h], key=lambda r: r["comment_id"])
            n2 = min(len(rs), alloc[h])
            idx = rng.choice(len(rs), n2, replace=False)
            p2 = n2 / len(rs)
            for i in sorted(idx):
                r = rs[i]
                out.append(
                    {
                        "comment_id": r["comment_id"],
                        "story_id": r["story_id"],
                        "stratum": r["stratum"],
                        "half": r["half"],
                        "phase": kind,
                        "w1": r["weight"],
                        "p2": p2,
                        "weight": r["weight"] / p2,
                        "firsthand_p": r["firsthand_p"],
                    }
                )
    return out


def test_draw_phase2_matches_reference_draw(pilot_repo):  # noqa: F811
    # n_pos=60 caps stratum A (share 42.9 > 40 rows); n_neg=35 caps the neg
    # A stratum too (share 14 > 10 rows), so both phases redistribute.
    t = _write_screen_table()
    tbl = phase2.draw_phase2(
        "scr-1",
        "fac-ref",
        n_pos=60,
        n_neg=35,
        cutoff=0.7,
        seed=20260931,
        snapshot_id=SNAPSHOT_ID,
    )
    expected = _reference_draw(
        t, n_pos=60, n_neg=35, cutoff=0.7, seed=20260931
    )
    got = tbl.to_pylist()
    assert [r["comment_id"] for r in got] == [
        r["comment_id"] for r in expected
    ]
    assert [r["p2"] for r in got] == [r["p2"] for r in expected]
    assert [r["weight"] for r in got] == [r["weight"] for r in expected]
    assert got == expected


def test_draw_phase2_every_stratum_capped_returns_all_rows(
    pilot_repo,  # noqa: F811
):
    # n_total larger than the whole population: every stratum caps at its
    # size, every row is drawn with p2 == 1.
    t = _write_screen_table()
    tbl = phase2.draw_phase2(
        "scr-1",
        "fac-all",
        n_pos=10_000,
        n_neg=10_000,
        seed=3,
        snapshot_id=SNAPSHOT_ID,
    )
    rows = tbl.to_pylist()
    assert len(rows) == len(t)
    assert {r["comment_id"] for r in rows} == {r["comment_id"] for r in t}
    for r in rows:
        assert r["p2"] == 1.0
        assert r["weight"] == r["w1"]


def _write_facets_sample(sample_id, ids, snapshot_id=SNAPSHOT_ID, seed=7):
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "comment_id": int(c),
            "story_id": 9_000_100_000,
            "stratum": A,
            "half": "explore",
            "phase": "pos",
            "w1": 2.0,
            "p2": 0.5,
            "weight": 4.0,
            "firsthand_p": 0.9,
        }
        for c in ids
    ]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=phase2.PHASE2_SCHEMA),
        paths.sample_path(sample_id),
    )
    (paths.SAMPLES / f"{sample_id}.json").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "seed": seed,
                "parent_run": "scr-1",
                "cutoff": 0.7,
                "n_pos": len(ids),
                "n_neg": 0,
                "snapshot_id": snapshot_id,
                "design": "two-phase",
            },
            indent=1,
        )
        + "\n"
    )


def _snapshot_ids(n):
    comments = pq.read_table(
        paths.snapshot_dir(SNAPSHOT_ID) / "comments.parquet",
        columns=["id", "eligible"],
    )
    eligible = [
        r["id"] for r in comments.to_pylist() if r["eligible"]
    ]
    return sorted(eligible)[:n]


def test_estimate_phase2_scales_probe(pilot_repo, capsys):  # noqa: F811
    ids = _snapshot_ids(10)
    _write_facets_sample("fac-x", ids)
    est = phase2.estimate_phase2("fac-x", probe_max=4)
    assert est["calls"] == 10
    assert est["probe"] == len(ids[:: max(1, 10 // 4)])  # step 2 -> 5
    assert est["est_usd"] > 0
    # estimate does not create a run dir
    assert not paths.run_dir("fac-run").exists()


def test_run_phase2_dry_run_only_prints_estimate(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    ids = _snapshot_ids(10)
    _write_facets_sample("fac-x", ids)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    out = phase2.run_phase2("fac-x", "fac-run", chunk=4, yes=False)
    printed = capsys.readouterr().out
    assert json.loads(printed)["calls"] == 10
    assert out["dispatched"] is False
    assert seen == []
    assert not paths.run_dir("fac-run").exists()


def test_run_phase2_chunks_and_rpm(pilot_repo, monkeypatch, capsys):  # noqa: F811
    ids = _snapshot_ids(10)
    _write_facets_sample("fac-x", ids)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)
    chunks = []
    monkeypatch.setattr(
        phase2, "_report", lambda n, out: chunks.append((n, out["completed"]))
    )
    out = phase2.run_phase2(
        "fac-x", "fac-run", chunk=4, rpm=120, yes=True
    )
    assert out["dispatched"] is True
    assert out["run"]["completed"] == 10
    assert out["run"]["new_requests"] == 10
    assert len(seen) == 10
    assert chunks == [(0, 4), (1, 4), (2, 2)]
    # rpm 120 -> one request every 0.5s; 10 requests -> ~4.5s of virtual wait.
    assert clock.ns == pytest.approx(4.5e9, rel=0.05)
    manifest = json.loads(
        (paths.run_dir("fac-run") / "run_manifest.json").read_text()
    )
    assert manifest["budget"] == "facets"
    assert manifest["question_sets"][0]["label"] == "facets@2"


def test_run_phase2_resumes_after_interrupt(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    ids = _snapshot_ids(10)
    _write_facets_sample("fac-x", ids)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    calls = {"n": 0}
    real = phase2._report

    def boom(n, out):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("interrupt")
        real(n, out)

    monkeypatch.setattr(phase2, "_report", boom)
    with pytest.raises(RuntimeError, match="interrupt"):
        phase2.run_phase2("fac-x", "fac-run", chunk=4, yes=True)
    assert len(seen) == 8  # two chunks of 4 landed

    monkeypatch.setattr(phase2, "_report", real)
    out = phase2.run_phase2("fac-x", "fac-run", chunk=4, yes=True)
    assert len(seen) == 10  # exactly 2 new requests
    assert out["run"]["skipped_completed"] == 8
    assert out["run"]["new_requests"] == 2
    answers = pq.read_table(paths.run_dir("fac-run") / "answers")
    answered = sorted(
        {r["comment_id"] for r in answers.to_pylist()}
    )
    assert answered == sorted(ids)


def test_facets_cli_parse(pilot_repo):  # noqa: F811
    parser = cli.build_parser()
    for argv in (
        ["facets", "draw", "--screen-run", "s", "--sample-id", "f", "--seed", "1"],
        ["facets", "estimate", "--sample-id", "f"],
        ["facets", "run", "--sample-id", "f", "--run", "r"],
    ):
        args = parser.parse_args(argv)
        assert callable(args.func)
    args = parser.parse_args(
        ["facets", "run", "--sample-id", "f", "--run", "r"]
    )
    assert args.budget == "facets"
    assert args.yes is False


def test_run_phase2_validates_args(pilot_repo):  # noqa: F811
    _write_facets_sample("fac-x", _snapshot_ids(4))
    with pytest.raises(ValueError):
        phase2.run_phase2("fac-x", "r", rpm=0)
    with pytest.raises(ValueError):
        phase2.run_phase2("fac-x", "r", rpm=1500)
    with pytest.raises(ValueError):
        phase2.run_phase2("fac-x", "r", chunk=0)

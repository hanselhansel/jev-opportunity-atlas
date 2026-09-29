"""L22 22.1: pooled, time-balanced allocation and `sample draw-pooled`.

Pooled allocation drops the half-year from v2 strata so both halves of a
pooled stratum get the same sampling rate, then splits the pooled allocation
back across H1/H2 in proportion to N. Thin pooled cells borrow pilot
observations from pain|lbin|, then pain|, then all.
"""

import hashlib
import json

import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
from atlas.sampling import pooled, yield_alloc
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)


def test_both_halves_share_one_sampling_rate():
    N = {
        "pain|L1|H1|ask": 3000,
        "pain|L1|H2|ask": 1200,
        "nopain|L0|H1|story": 800,
        "nopain|L0|H2|story": 400,
    }
    obs_p = {
        "pain|L1|ask": [True] * 30 + [False] * 30,
        "nopain|L0|story": [False] * 40,
    }
    obs_c = {
        "pain|L1|ask": [500.0] * 60,
        "nopain|L0|story": [300.0] * 40,
    }
    res = pooled.pooled_allocation(N, obs_p, obs_c, 400_000, 0.02, 1.0)
    alloc = res["alloc"]
    assert set(alloc) == set(N)
    # The high-yield pooled stratum draws well above the floor: both halves
    # share one rate, |a/Na - b/Nb| <= .5/Na + .5/Nb (rounding only).
    a, b = "pain|L1|H1|ask", "pain|L1|H2|ask"
    assert abs(alloc[a] / N[a] - alloc[b] / N[b]) <= (
        0.5 / N[a] + 0.5 / N[b] + 1e-12
    )
    # The zero-yield pooled stratum sits at the min_n floor in both halves.
    assert alloc["nopain|L0|H1|story"] == alloc["nopain|L0|H2|story"] == 30


def test_thin_pooled_cells_borrow_exactly_like_reference():
    # pain|L1|ask has 5 obs (< min_pilot_n) -> borrows "pain|L1|" (5+15 obs).
    # nopain|L0|story has 10 -> "nopain|L0|" is 10 -> borrows "nopain|" (30).
    # nopain|L2|other has 20 -> self.
    # show|L3|ask has no obs anywhere in its prefixes -> "all".
    obs_p = {
        "pain|L1|ask": [True] * 5,
        "pain|L1|show": [False] * 15,
        "nopain|L0|story": [True] * 3 + [False] * 7,
        "nopain|L2|other": [True] * 10 + [False] * 10,
    }
    obs_c = {
        "pain|L1|ask": [100.0] * 5,
        "pain|L1|show": [300.0] * 15,
        "nopain|L0|story": [200.0] * 10,
        "nopain|L2|other": [400.0] * 20,
    }
    N = {
        "pain|L1|H1|ask": 100,
        "nopain|L0|H1|story": 100,
        "nopain|L2|H2|other": 100,
        "show|L3|H2|ask": 50,
    }
    res = pooled.pooled_allocation(N, obs_p, obs_c, 80_000, 0.02, 1.0)
    assert res["levels"]["pain|L1|H1|ask"]["p"] == "pain|L1|"
    assert res["p"]["pain|L1|H1|ask"] == pytest.approx(5 / 20)
    assert res["levels"]["nopain|L0|H1|story"]["p"] == "nopain|"
    assert res["p"]["nopain|L0|H1|story"] == pytest.approx(13 / 30)
    assert res["levels"]["nopain|L2|H2|other"]["p"] == "nopain|L2|other"
    assert res["levels"]["show|L3|H2|ask"]["p"] == "all"
    all_vals = [v for vs in obs_p.values() for v in vs]
    assert res["p"]["show|L3|H2|ask"] == pytest.approx(
        sum(all_vals) / len(all_vals)
    )
    # c borrows the same way, then scales by cost_scale.
    assert res["levels"]["pain|L1|H1|ask"]["c"] == "pain|L1|"
    assert res["c"]["pain|L1|H1|ask"] == pytest.approx(250.0 * 1.0)


def test_thin_cells_fall_through_to_all_below_min_n():
    obs_p = {"pain|L1|ask": [True] * 4}
    obs_c = {"pain|L1|ask": [50.0] * 4}
    N = {"nopain|L9|H2|other": 60}
    res = pooled.pooled_allocation(N, obs_p, obs_c, 5_000, 0.02, 2.0)
    assert res["levels"]["nopain|L9|H2|other"] == {"p": "all", "c": "all"}
    assert res["p"]["nopain|L9|H2|other"] == 1.0
    assert res["c"]["nopain|L9|H2|other"] == 100.0


def test_expected_tokens_within_0_1_percent_of_budget():
    N = {
        "pain|L1|H1|ask": 50_000,
        "pain|L1|H2|ask": 20_000,
        "nopain|L0|H1|story": 30_000,
        "nopain|L0|H2|story": 30_000,
    }
    obs_p = {
        "pain|L1|ask": [True] * 60,
        "nopain|L0|story": [False] * 40,
    }
    obs_c = {
        "pain|L1|ask": [500.0] * 60,
        "nopain|L0|story": [300.0] * 40,
    }
    # Partial fill well above every floor: leftover is < min c_h.
    res = pooled.pooled_allocation(N, obs_p, obs_c, 10_000_050, 0.02, 1.0)
    exp = yield_alloc.expected_tokens(res["alloc"], res["c"])
    assert abs(exp - 10_000_050) <= 0.001 * 10_000_050


def test_no_alphabetical_half_imbalance():
    """Plain allocate_by_yield fills H1 before H2 (label order) when p and c
    tie; the pooled split must not reproduce that."""
    N = {"pain|L1|H1|ask": 1000, "pain|L1|H2|ask": 1000}
    flat_p = {h: 1.0 for h in N}
    flat_c = {h: 400.0 for h in N}
    budget = 224_000  # floors (30*2*400) plus 500 extra comments at 400
    plain = yield_alloc.allocate_by_yield(dict(N), flat_p, flat_c, budget, 0.02)
    assert plain["pain|L1|H1|ask"] == 530
    assert plain["pain|L1|H2|ask"] == 30  # the imbalance this lane removes

    obs_p = {"pain|L1|ask": [True] * 40}
    obs_c = {"pain|L1|ask": [400.0] * 40}
    res = pooled.pooled_allocation(N, obs_p, obs_c, budget, 0.02, 1.0)
    assert res["alloc"]["pain|L1|H1|ask"] == res["alloc"]["pain|L1|H2|ask"]


def _make_pilot_run(monkeypatch, seed=7):
    """Real pilot draw + mocked screen run -> sample, answers, ledger."""
    from atlas.pilot import stages
    from atlas.pilot.draw import pilot_draw

    pilot_draw(SNAPSHOT_ID, n_target=120, min_per_stratum=10, seed=seed)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    stages.run_screen(f"pilot-{seed}", f"pilot-{seed}", yes=True)
    return f"pilot-{seed}"


def _run_cli(*argv):
    args = cli.build_parser().parse_args(list(argv))
    args.func(args)


def _draw_pooled_args(sample_id, pilot_run):
    return (
        "sample",
        "draw-pooled",
        "--pilot-run",
        pilot_run,
        "--budget-usd",
        "0.01",
        "--cost-scale",
        "0.424",
        "--cutoff",
        "0.7",
        "--seed",
        "20260930",
        "--sample-id",
        sample_id,
    )


def test_draw_pooled_writes_manifest_and_is_byte_identical(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    pilot_run = _make_pilot_run(monkeypatch)
    capsys.readouterr()
    _run_cli(*_draw_pooled_args("main-x", pilot_run))
    out = capsys.readouterr().out
    assert "n=" in out and "expected tokens" in out
    summary = json.loads(out.strip().rsplit("\n", 1)[-1])
    assert summary["rows"] > 0

    sample_path = paths.sample_path("main-x")
    sidecar_path = paths.SAMPLES / "main-x.json"
    assert sample_path.exists() and sidecar_path.exists()
    sha1 = hashlib.sha256(sample_path.read_bytes()).hexdigest()

    meta = json.loads(sidecar_path.read_text())
    assert meta["seed"] == 20260930
    assert meta["seeds_by_batch"] == {"1": 20260930}
    assert meta["frame_snapshot_id"] == SNAPSHOT_ID
    assert meta["pilot_run"] == pilot_run
    assert meta["budget_usd"] == 0.01
    assert meta["cost_scale"] == 0.424
    assert meta["cutoff"] == 0.7
    design = meta["design"]
    for key in (
        "pain_patterns_version",
        "floor_rate",
        "min_n",
        "budget_tokens",
        "p_h",
        "c_h",
        "inputs_source",
        "input_levels",
        "allocation",
        "expected_positives",
        "expected_tokens",
        "largest_weight",
    ):
        assert key in design
    assert "pooled across half-years" in design["inputs_source"]
    # Pooled input levels use the reference's coarse labels.
    assert set(design["input_levels"]) == set(design["allocation"])

    table = pq.read_table(sample_path)
    rows = table.to_pylist()
    sizes = {}
    for r in rows:
        sizes.setdefault(r["stratum"], 0)
    # weights invert the realized inclusion probability
    for r in rows:
        assert r["inclusion_prob"] > 0
        assert r["weight"] == pytest.approx(1 / r["inclusion_prob"])

    # Second identical run reuses the file; bytes are identical.
    _run_cli(*_draw_pooled_args("main-x", pilot_run))
    capsys.readouterr()
    assert hashlib.sha256(sample_path.read_bytes()).hexdigest() == sha1
    meta2 = json.loads(sidecar_path.read_text())
    assert meta2["sha256"] == sha1

    # A different seed on the same id refuses to overwrite.
    with pytest.raises(Exception, match="different draw parameters|exists"):
        _run_cli(
            *(
                list(_draw_pooled_args("main-x", pilot_run))[:-2]
                + ["--seed", "99", "--sample-id", "main-x"]
            )
        )

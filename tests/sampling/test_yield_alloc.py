import pytest

from atlas.sampling.yield_alloc import allocate_by_yield


def test_allocation_prefers_high_yield_but_respects_floor_and_budget():
    N = {"pain": 100_000, "nopain": 900_000}
    p = {"pain": 0.30, "nopain": 0.03}  # expected firsthand rate (from the pilot)
    c = {"pain": 500.0, "nopain": 400.0}  # expected tokens per screen call
    alloc = allocate_by_yield(N, p, c, budget_tokens=100_000_000, floor_rate=0.02)
    spent = sum(alloc[h] * c[h] for h in N)
    assert spent <= 100_000_000
    assert alloc["nopain"] >= 0.02 * N["nopain"]  # floor holds
    assert alloc["pain"] / N["pain"] > alloc["nopain"] / N["nopain"]
    assert all(0 < alloc[h] <= N[h] for h in N)


def test_floor_alone_exceeding_budget_raises():
    with pytest.raises(ValueError):
        allocate_by_yield(
            {"a": 10_000_000},
            {"a": 0.1},
            {"a": 500.0},
            budget_tokens=1_000_000,
            floor_rate=0.05,
        )


def test_expected_positives_reported():
    from atlas.sampling.yield_alloc import expected_positives

    assert expected_positives({"a": 100, "b": 10}, {"a": 0.1, "b": 0.5}) == (
        pytest.approx(15)
    )


def test_tie_break_is_lexicographic():
    N = {"b": 1_000, "a": 1_000}
    p = {"a": 0.5, "b": 0.5}
    c = {"a": 100.0, "b": 100.0}
    # min_n floors only cover 20 rows; 100 spare tokens top up one stratum.
    alloc = allocate_by_yield(
        N, p, c, budget_tokens=2_100, floor_rate=0.01, min_n=10
    )
    assert alloc == {"a": 11, "b": 10}


def test_empty_stratum_gets_zero():
    N = {"a": 1_000, "z": 0}
    p = {"a": 0.5, "z": 0.9}
    c = {"a": 100.0, "z": 100.0}
    alloc = allocate_by_yield(N, p, c, budget_tokens=10_000, floor_rate=0.01)
    assert alloc["z"] == 0
    assert alloc["a"] > 0


def test_invalid_inputs_raise():
    good = ({"a": 100}, {"a": 0.1}, {"a": 10.0})
    with pytest.raises(ValueError):
        allocate_by_yield(*good, budget_tokens=1_000, floor_rate=0.0)
    with pytest.raises(ValueError):
        allocate_by_yield(*good, budget_tokens=1_000, floor_rate=1.5)
    with pytest.raises(ValueError):
        allocate_by_yield(
            {"a": 100}, {"a": -0.1}, {"a": 10.0},
            budget_tokens=1_000, floor_rate=0.5,
        )
    with pytest.raises(ValueError):
        allocate_by_yield(
            {"a": 100}, {"a": 0.1}, {"a": 0.0},
            budget_tokens=1_000, floor_rate=0.5,
        )
    with pytest.raises(ValueError):
        allocate_by_yield(
            {"a": 100}, {"a": 0.1, "b": 0.2}, {"a": 10.0},
            budget_tokens=1_000, floor_rate=0.5,
        )


def test_reporting_helpers():
    from atlas.sampling.yield_alloc import expected_tokens, largest_weight

    alloc = {"a": 100, "b": 10, "z": 0}
    assert expected_tokens(alloc, {"a": 5.0, "b": 2.0, "z": 9.0}) == 520.0
    assert largest_weight(alloc, {"a": 200, "b": 400, "z": 50}) == 40.0

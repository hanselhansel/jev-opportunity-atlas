"""L17 17.2: --cost-scale multiplies every pilot c_h before allocating."""

import json

import pytest

from atlas.sampling import yield_alloc
from tests.sampling.test_yield_alloc import repo_v2, run_cli  # noqa: F401


def test_scale_costs_unit():
    c = {"a": 591.0, "b": 591.0}
    scaled = yield_alloc.scale_costs(c, 0.425)
    assert scaled == {
        "a": pytest.approx(251.175),
        "b": pytest.approx(251.175),
    }
    assert c == {"a": 591.0, "b": 591.0}
    with pytest.raises(ValueError):
        yield_alloc.scale_costs(c, 0)
    with pytest.raises(ValueError):
        yield_alloc.scale_costs(c, -0.5)


def test_allocation_at_scaled_cost():
    N = {"a": 10_000_000, "b": 10_000_000}
    p = {"a": 0.2, "b": 0.1}
    c = {"a": 591.0, "b": 591.0}
    base = yield_alloc.allocate_by_yield(
        N, p, c, budget_tokens=5_000_000, floor_rate=1e-6, min_n=30
    )
    scaled = yield_alloc.allocate_by_yield(
        N, p, yield_alloc.scale_costs(c, 0.425),
        budget_tokens=5_000_000, floor_rate=1e-6, min_n=30,
    )
    assert sum(scaled.values()) / sum(base.values()) == pytest.approx(
        1 / 0.425, rel=0.01
    )


def test_allocate_v2_cost_scale(repo_v2, capsys):  # noqa: F811
    run_cli(
        "sample", "allocate-v2",
        "--pilot-run", "pilot-x", "--budget-usd", "0.00051",
    )
    plain = json.loads(capsys.readouterr().out)
    assert plain["cost_scale"] == 1.0
    assert plain["cost_scale_source"] is None

    run_cli(
        "sample", "allocate-v2",
        "--pilot-run", "pilot-x", "--budget-usd", "0.00051",
        "--cost-scale", "0.425",
    )
    out = json.loads(capsys.readouterr().out)
    assert out["cost_scale"] == 0.425
    assert out["cost_scale_source"] == (
        "pilot:pilot-x-packed tokens/comment ÷ single"
    )
    for h in plain["c_h"]:
        assert out["c_h"][h] == pytest.approx(plain["c_h"][h] * 0.425)
    # Same budget at cheaper costs buys more comments.
    assert sum(out["allocation"].values()) > sum(plain["allocation"].values())


def test_design_v2_cost_scale(repo_v2, capsys):  # noqa: F811
    run_cli(
        "sample", "design-v2",
        "--pilot-run", "pilot-x", "--budget-usd", "0.00051",
        "--sample-id", "v2scale", "--cost-scale", "0.425",
    )
    json.loads(capsys.readouterr().out)
    from atlas import paths

    meta = json.loads((paths.SAMPLES / "v2scale.json").read_text())
    assert meta["cost_scale"] == 0.425
    assert meta["cost_scale_source"] == (
        "pilot:pilot-x-packed tokens/comment ÷ single"
    )

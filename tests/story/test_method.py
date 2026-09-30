"""S8b: method section — the saved planted result file wins over the
recompute fallback, and ``total_usd`` sums every listed ledger."""

import json

import pytest

from atlas import paths
from tests.story import world


def test_planted_recovery_prefers_saved_json(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import method

    run_dir = paths.run_dir(world.PLANTED_RUN)
    (run_dir / f"planted-{world.TV}+planted-v1.json").write_text(
        json.dumps({"recovery": 0.5, "n_planted": 50})
    )
    got = method._planted_recovery({world.PLANTED_RUN: "checks"})
    assert got == 0.5


def test_planted_recovery_json_without_assignments(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import method

    run_dir = paths.run_dir("planted-only")
    run_dir.mkdir(parents=True)
    (run_dir / "planted-t3+planted-v1.json").write_text(
        json.dumps({"recovery": 0.9})
    )
    got = method._planted_recovery({"planted-only": "checks"})
    assert got == 0.9


def test_planted_recovery_recompute_fallback(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import method

    # No planted-*.json: recovery comes from the saved assignments parquet.
    got = method._planted_recovery({world.PLANTED_RUN: "checks"})
    assert got == 1.0


def test_total_usd_sums_listed_ledgers(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.inference import ledger
    from atlas.story import method

    phases = method.run_phases("configs/run_phases.toml")
    assert f"{world.ASSIGN_RUN}/solutions" in phases
    assert "builders-syn" in phases
    expected = sum(
        ledger.summarize(paths.ledger_path(rid))["calculated_usd"]
        for rid in phases
    )
    m = method.build_method(
        "configs/run_phases.toml",
        world.AUDIT_RUN,
        world.BENCH_RUN,
        "runs/robust-screen-compare.json",
        "runs/robust-assign-compare.json",
    )
    assert {r["run"] for r in m["runs"]} == set(phases)
    assert m["total_usd"] == pytest.approx(expected)

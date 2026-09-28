import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
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


# --- L10 task 10.5: pilot readers and the allocate-v2 CLI -----------------

REPO_ROOT = Path(__file__).resolve().parents[2]

# ids 1..50 -> pain|L1|H1|ask, 51..100 -> pain|L1|H2|ask,
# 101..150 -> nopain|L0|H1|story, 151..200 -> nopain|L0|H2|story
PILOT_COVERAGE = (
    [(9_000_000_000 + i, 0.9) for i in range(1, 16)]
    + [(9_000_000_000 + i, 0.8) for i in range(51, 56)]
    + [(9_000_000_000 + i, 0.1) for i in range(101, 106)]
    + [(9_000_000_000 + i, 0.2) for i in range(151, 156)]
    + [(9_100_000_001, 0.9)]  # injected: not in the frame, must be dropped
)


def _answers_table():
    n = len(PILOT_COVERAGE) + 1
    rows = {
        "run_id": ["pilot-x"] * n,
        "comment_id": [c for c, _ in PILOT_COVERAGE] + [9_000_000_002],
        "question_set": ["screen@0"] * n,
        "question_id": ["firsthand_problem"] * (n - 1) + ["some_other_q"],
        "qtype": ["noul"] * n,
        "noul": [v for _, v in PILOT_COVERAGE] + [0.0],
        "choice": [None] * n,
        "score": [None] * n,
        "probabilities_json": [None] * n,
        "confidence": [None] * n,
        "model_returned": ["jev-1.13.0"] * n,
        "request_id": [f"req-{i}" for i in range(n)],
        "logical_call_id": [f"lc-{i}" for i in range(n)],
        "cache_hit": [False] * n,
    }
    return pa.table(rows, schema=contracts.ANSWERS)


def _ledger_row(cid, cost_class="calculated", input_tokens=100):
    row = {
        "run_id": "pilot-x",
        "logical_call_id": f"lc-{cid}-{cost_class}",
        "attempt": 1,
        "comment_id": cid,
        "question_set": "screen@0",
        "question_count": 2,
        "input_hash": f"hash-{cid}",
        "model_requested": "jev-1.13.0",
        "model_returned": "jev-1.13.0",
        "request_id": f"req-{cid}",
        "started_at": "2026-09-29T00:00:00Z",
        "ended_at": "2026-09-29T00:00:01Z",
        "queue_ms": 0,
        "request_ms": 900,
        "backoff_ms": 0,
        "http_status": 200,
        "error_type": None,
        "validation": "ok",
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "cache": "miss",
        "price_version": "typesafe-2026-09-28",
        "cost_usd": 0.0000042,
        "cost_class": cost_class,
    }
    return {k: row[k] for k in contracts.LEDGER_FIELDS}


@pytest.fixture
def repo_v2(tmp_path, monkeypatch):
    snap = tmp_path / "snapshots" / "snapv2"
    snap.mkdir(parents=True)
    ids = list(range(9_000_000_001, 9_000_000_201))
    comments = pa.table(
        {
            "id": ids,
            "story_id": [9_000_000_900] * 200,
            "period": ["P01"] * 50 + ["P08"] * 50 + ["P01"] * 50 + ["P08"] * 50,
            "thread_type": ["ask_hn"] * 100 + ["story"] * 100,
            "text_norm": ["We spent hours on a workaround."] * 100
            + ["Nice release notes."] * 100,
            "word_count": [20] * 100 + [10] * 100,
            "eligible": [True] * 200,
        }
    )
    stories = pa.table(
        {"id": [9_000_000_900], "thread_type": ["ask_hn"]}
    )
    pq.write_table(comments, snap / "comments.parquet")
    pq.write_table(stories, snap / "stories.parquet")

    run = tmp_path / "runs" / "pilot-x"
    (run / "answers").mkdir(parents=True)
    pq.write_table(_answers_table(), run / "answers" / "part-000.parquet")
    ledger_rows = [
        _ledger_row(cid) for cid, _ in PILOT_COVERAGE
    ]
    # Non-calculated rows and null tokens are ignored.
    ledger_rows.append(
        _ledger_row(9_000_000_001, cost_class="replay", input_tokens=999)
    )
    (run / "ledger.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in ledger_rows)
    )

    configs = tmp_path / "configs"
    configs.mkdir()
    # Test-local sampling_v2.toml: small floor/min_n/min_pilot_n so the
    # allocation on a 200-comment fixture is nontrivial.
    (configs / "sampling_v2.toml").write_text(
        "floor_rate = 0.1\n"
        "min_n = 5\n"
        "seed = 7\n"
        'screen_question_set = "screen@0"\n'
        'firsthand_question = "firsthand_problem"\n'
        "firsthand_threshold = 0.5\n"
        "min_pilot_n = 10\n"
    )
    (configs / "prices.toml").write_text(
        (REPO_ROOT / "configs" / "prices.toml").read_text()
    )
    (configs / "acquisition.toml").write_text('snapshot_id = "snapv2"\n')

    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "data" / "samples")
    monkeypatch.setattr(paths, "MANIFESTS", tmp_path / "manifests")
    monkeypatch.setattr(paths, "CONFIGS", configs)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    return tmp_path


def run_cli(*argv):
    from atlas import cli

    args = cli.build_parser().parse_args(list(argv))
    args.func(args)


def _frame_v2():
    from atlas.sampling.design_v2 import build_frame_v2

    sdir = paths.snapshot_dir("snapv2")
    comments = pq.read_table(sdir / "comments.parquet")
    stories = pq.read_table(sdir / "stories.parquet")
    return build_frame_v2(comments, stories)


def test_pilot_inputs_level_fallback(repo_v2):
    import tomllib

    from atlas.sampling.yield_alloc import pilot_inputs

    cfg = tomllib.loads((paths.CONFIGS / "sampling_v2.toml").read_text())
    p, c, levels = pilot_inputs(_frame_v2(), "pilot-x", cfg)
    # Full stratum has >= min_pilot_n pilot comments.
    assert levels["pain|L1|H1|ask"]["p"] == "pain|L1|H1|ask"
    assert p["pain|L1|H1|ask"] == pytest.approx(1.0)
    assert c["pain|L1|H1|ask"] == pytest.approx(100.0)
    # Fewer than min_pilot_n at the full level -> coarser levels.
    assert levels["pain|L1|H2|ask"]["p"] == "pain|L1"
    assert levels["nopain|L0|H1|story"]["p"] == "nopain|L0"
    assert levels["nopain|L0|H2|story"]["c"] == "nopain|L0"
    assert p["nopain|L0|H2|story"] == pytest.approx(0.0)


def test_pilot_inputs_empty_run_raises(repo_v2):
    import tomllib

    from atlas.sampling.yield_alloc import pilot_inputs

    cfg = tomllib.loads((paths.CONFIGS / "sampling_v2.toml").read_text())
    with pytest.raises(ValueError, match="run-nope"):
        pilot_inputs(_frame_v2(), "run-nope", cfg)


def test_allocate_v2_cli(repo_v2, capsys):
    run_cli(
        "sample",
        "allocate-v2",
        "--pilot-run",
        "pilot-x",
        "--budget-usd",
        "0.00051",
    )
    out = json.loads(capsys.readouterr().out)
    for key in (
        "snapshot",
        "pilot_run",
        "budget_usd",
        "budget_tokens",
        "price_version",
        "floor_rate",
        "min_n",
        "allocation",
        "N_h",
        "p_h",
        "c_h",
        "input_levels",
        "expected_positives",
        "expected_tokens",
        "expected_usd",
        "largest_weight",
    ):
        assert key in out
    assert out["snapshot"] == "snapv2"
    assert out["pilot_run"] == "pilot-x"
    assert out["price_version"] == "typesafe-2026-09-28"
    assert out["expected_tokens"] <= out["budget_tokens"]
    alloc, sizes = out["allocation"], out["N_h"]
    assert all(0 < alloc[h] <= sizes[h] for h in sizes)
    pain_rates = [alloc[h] / sizes[h] for h in sizes if h.startswith("pain|")]
    nopain_rates = [alloc[h] / sizes[h] for h in sizes if h.startswith("nopain|")]
    assert min(pain_rates) > max(nopain_rates)
    # allocate-v2 never draws or writes sample files.
    assert not paths.SAMPLES.exists() or not list(paths.SAMPLES.iterdir())

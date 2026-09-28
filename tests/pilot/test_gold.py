"""Task 7.5: calibration + audit queues and the GOLD_DRAWS records."""

import re

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.cli import build_parser
from atlas.evaluation.queue import load_queue, queue_path, read_answers, sequence
from atlas.evaluation.store import LabelStore, labels_path
from atlas.pilot import gold, stages
from atlas.pilot.draw import pilot_draw
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)

SAMPLE_ID = "pilot-7"
RUN_ID = "pilot-7"


def _noul(state, qid):
    """Spread nouls across all three bands: (comment id % 20) / 20. The id
    rides in every text field as `ref <id>.`; facets@1 has no `comment`
    field, so scan all string values in the state."""
    stack = list(state.values())
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, str):
            m = re.search(r"ref (\d+)", value)
            if m:
                return (int(m.group(1)) % 20) / 20
    return 0.0


def _pipeline(monkeypatch, facets=True):
    pilot_draw(SNAPSHOT_ID, n_target=400, min_per_stratum=20, seed=7)
    mock_env(monkeypatch, make_transport(noul=_noul))
    stages.run_screen(SAMPLE_ID, RUN_ID, yes=True)
    if facets:
        stages.run_facets(RUN_ID, yes=True)


def _approve_rubric():
    (paths.CONFIGS / "rubric.v1.md").write_text(
        "---\nversion: v1\nstatus: approved\n---\n", encoding="utf-8"
    )


def _label_args(*extra):
    return build_parser().parse_args(
        [
            "label",
            "run",
            "--label-set",
            "calibration",
            "--sample",
            SAMPLE_ID,
            "--run",
            RUN_ID,
            *extra,
        ]
    )


def test_label_run_reuses_the_pilot_queue(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _pipeline(monkeypatch)
    gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    _approve_rubric()
    qpath = queue_path("calibration")
    before = qpath.read_bytes()
    capsys.readouterr()

    args = _label_args("--no-launch")
    args.func(args)
    assert "reusing queue" in capsys.readouterr().out
    assert qpath.read_bytes() == before
    queue = load_queue(qpath)
    assert len(sequence(queue)) == len(queue["ids"]) + len(queue["repeats"])


def test_calibration_queue_matches_label_run_format(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    _pipeline(monkeypatch, facets=False)
    _approve_rubric()
    args = _label_args("--no-launch")
    args.func(args)
    theirs = load_queue(queue_path("calibration"))
    queue_path("calibration").unlink()
    capsys.readouterr()

    gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    ours = load_queue(queue_path("calibration"))
    assert ours.pop("created_at") != theirs.pop("created_at")
    assert ours == theirs


def test_top_up_ids_carry_their_own_seed(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _pipeline(monkeypatch)
    gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    _approve_rubric()
    capsys.readouterr()
    args = _label_args("--top-up", "10", "--no-launch")
    args.func(args)
    queue = load_queue(queue_path("calibration"))
    top = queue["top_ups"][0]
    assert len(top["ids"]) == 10

    gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    rows = pq.read_table(paths.LABELS / "gold_draws.parquet").to_pylist()
    cal = {r["comment_id"]: r for r in rows if r["label_set"] == "calibration"}
    assert len(cal) == len(queue["ids"])
    for cid in top["ids"]:
        assert cal[cid]["seed"] == top["seed"]
    base_ids = set(queue["ids"]) - set(top["ids"])
    assert all(r["seed"] == queue["seed"] for c, r in cal.items() if c in base_ids)


def test_gold_draws_rows(pilot_repo, monkeypatch):  # noqa: F811
    _pipeline(monkeypatch)
    gpath = paths.LABELS / "gold_draws.parquet"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    held = {
        "label_set": "heldout",
        "comment_id": 9_000_000_001,
        "draw_stratum": "hand",
        "selection_prob": 1.0,
        "seed": 0,
        "purpose": "estimate",
    }
    pq.write_table(
        pa.Table.from_pylist([held], schema=contracts.GOLD_DRAWS), gpath
    )

    out = gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    assert out["audit"] is not None
    table = pq.read_table(gpath)
    assert table.schema.equals(contracts.GOLD_DRAWS)
    rows = table.to_pylist()
    cal = [r for r in rows if r["label_set"] == "calibration"]
    audit = [r for r in rows if r["label_set"] == "audit"]
    assert [r for r in rows if r["label_set"] == "heldout"] == [held]

    cqueue = load_queue(queue_path("calibration"))
    band_of = {
        cid: b for b, info in cqueue["bands"].items() for cid in info["ids"]
    }
    assert len(cal) == len(cqueue["ids"])
    for r in cal:
        band = band_of[r["comment_id"]]
        assert r["draw_stratum"] == band
        assert r["selection_prob"] == pytest.approx(cqueue["rates"][band])
        assert r["seed"] == cqueue["seed"]
        assert r["purpose"] == "calibration"

    sel = {
        r["comment_id"]: r
        for r in pq.read_table(
            paths.run_dir(RUN_ID) / "facet_selection.parquet"
        ).to_pylist()
    }
    aqueue = load_queue(queue_path("audit"))
    n_pool = len(set(sel) - set(cqueue["ids"]))
    assert len(audit) == len(aqueue["ids"]) == min(50, n_pool)
    for r in audit:
        cid = r["comment_id"]
        assert r["draw_stratum"] == "faceted:" + sel[cid]["rule"]
        assert r["selection_prob"] == pytest.approx(
            len(aqueue["ids"]) / n_pool * sel[cid]["selection_prob"]
        )
        assert r["seed"] == aqueue["seed"]
        assert r["purpose"] == "audit"
    assert {r["comment_id"] for r in audit}.isdisjoint(
        {r["comment_id"] for r in cal}
    )

    # Rerun is idempotent: same rows, no duplicates.
    gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    again = pq.read_table(gpath).to_pylist()
    assert len(again) == len(rows)
    assert {tuple(sorted(r.items())) for r in again} == {
        tuple(sorted(r.items())) for r in rows
    }


def test_missing_facet_selection_skips_audit(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    _pipeline(monkeypatch, facets=False)
    out = gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    assert out["audit"] is None
    assert "audit" in capsys.readouterr().out
    assert queue_path("calibration").exists()
    rows = pq.read_table(paths.LABELS / "gold_draws.parquet").to_pylist()
    assert {r["label_set"] for r in rows} == {"calibration"}


def test_evaluate_calibration_with_labels(pilot_repo, monkeypatch):  # noqa: F811
    from atlas.evaluation.cli import evaluate

    _pipeline(monkeypatch, facets=False)
    gold.build_calibration(RUN_ID, SAMPLE_ID, seed=1)
    queue = load_queue(queue_path("calibration"))
    answers = read_answers(RUN_ID, "firsthand_problem")
    store = LabelStore(labels_path())
    for cid in queue["ids"]:
        store.add(
            comment_id=cid,
            label_set="calibration",
            question_id="firsthand_problem",
            value="yes" if answers[cid]["noul"] >= 0.5 else "no",
            rubric_version="v1",
            reviewer="test",
            started_at="2026-09-29T00:00:00+00:00",
            ended_at="2026-09-29T00:00:01+00:00",
            seconds=1.0,
        )
    report = evaluate("calibration", RUN_ID, n_boot=50)
    assert report["weighting"].startswith("1/rate[band]")
    assert report["n_labeled"] == len(queue["ids"])

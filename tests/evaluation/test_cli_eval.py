import json
import sys
import types

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.evaluation.queue import build_queue, queue_path, save_queue
from atlas.evaluation.store import LabelStore, labels_path, repeats_path

BASE = 9_000_000_000
N = 60


def _setup(tmp_path, monkeypatch, label_missing_answers=0):
    for name in ("LABELS", "SAMPLES", "RUNS"):
        monkeypatch.setattr(paths, name, tmp_path / name.lower())
    ids = [BASE + i for i in range(N)]
    scores = [(i % 20) / 20 + 0.01 for i in range(N)]
    paths.SAMPLES.mkdir(parents=True)
    pq.write_table(pa.table({
        "sample_id": ["s1"] * N, "comment_id": ids, "story_id": [BASE + 10_000 + i // 3 for i in range(N)],
        "stratum": ["x"] * N, "inclusion_prob": [0.5] * N, "weight": [2.0] * N,
        "batch": [1] * N, "draw_order": list(range(N)),
    }, schema=contracts.SAMPLE), paths.sample_path("s1"))
    answered = ids[label_missing_answers:]
    rows = {name: [] for name in contracts.ANSWERS.names}
    for cid in answered:
        for q, noul, choice in (("firsthand_problem", scores[cid - BASE], None),
                                ("account_type", None, "firsthand_account")):
            for name in contracts.ANSWERS.names:
                rows[name].append(None)
            rows["run_id"][-1], rows["comment_id"][-1], rows["question_id"][-1] = "r1", cid, q
            rows["noul"][-1], rows["choice"][-1] = noul, choice
    (paths.RUNS / "r1" / "answers").mkdir(parents=True)
    pq.write_table(pa.table(rows, schema=contracts.ANSWERS), paths.RUNS / "r1" / "answers" / "part-0.parquet")

    frame = pa.table({"comment_id": ids, "score": scores})
    q = build_queue(frame, None, seed=1, bands={"high": (0.5, 1.01), "low": (0.0, 0.5)},
                    band_sizes={"high": 20, "low": 10})
    q.update(label_set="calibration", sample_id="s1", run_id="r1", snapshot_id="snap", domain_ids=[])
    save_queue(q, queue_path("calibration"))
    store, reps = LabelStore(labels_path()), LabelStore(repeats_path())
    common = {"label_set": "calibration", "rubric_version": "v1", "reviewer": "hansel",
              "started_at": "t0", "ended_at": "t1", "seconds": 3.0}
    for k, cid in enumerate(q["ids"]):
        value = "unsure" if k == 0 else ("yes" if scores[cid - BASE] >= 0.5 else "no")
        store.add(comment_id=cid, question_id="firsthand_problem", value=value, **common)
        store.add(comment_id=cid, question_id="account_type", value="firsthand_account", **common)
    for cid in q["repeats"]:
        reps.add(comment_id=cid, question_id="firsthand_problem", value="yes", **common)

    items = types.ModuleType("atlas.sources.items")
    items.load_items = lambda snapshot_dir, cids: [
        {"comment_id": c, "comment": "I hate how our deploys keep breaking" if c % 2 else "Nice release."}
        for c in cids]
    monkeypatch.setitem(sys.modules, "atlas.sources.items", items)
    return q


def _run(*argv):
    args = cli.build_parser().parse_args(["eval", "run", *argv])
    args.func(args)


def test_eval_run_writes_report(tmp_path, monkeypatch, capsys):
    q = _setup(tmp_path, monkeypatch)
    _run("--label-set", "calibration", "--run", "r1", "--n-boot", "200")
    report = json.loads((paths.RUNS / "r1" / "eval_calibration.json").read_text())
    assert report["n_labeled"] == 30 and report["n_joined"] == 30 and report["n_unsure"] == 1
    assert report["n_yes"] + report["n_no"] == 29
    assert report["weighting"] == "1/rate[band] x sample design weight"
    assert report["clusters"] == "story_id"
    assert report["metrics"]["recall"] >= report["threshold"]["recall_lower_bound"]
    assert report["threshold"]["recall_lower_bound"] >= 0.9
    assert report["threshold"]["note"] == "calibration only; not a reported quality number"
    assert report["baseline"]["name"] == "keyword_v1" and report["baseline"]["n"] == 29
    assert report["intra_rater"]["firsthand_problem"]["n"] == len(q["repeats"])
    assert report["choices"]["account_type"]["accuracy"] == pytest.approx(1.0)
    assert len(report["reliability_bins"]) == 10
    assert report["stop_rule"]["met"] is False
    assert "--top-up 50" in capsys.readouterr().err


def test_eval_run_refuses_low_join_coverage(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch, label_missing_answers=N)
    with pytest.raises(SystemExit) as exc:
        _run("--label-set", "calibration", "--run", "r1", "--n-boot", "50")
    assert exc.value.code == 1
    assert "join coverage" in capsys.readouterr().err
    assert not (paths.RUNS / "r1" / "eval_calibration.json").exists()

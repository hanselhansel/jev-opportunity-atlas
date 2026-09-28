import json
import shutil
from pathlib import Path

import pytest

import atlas.cli
from atlas import paths
from tests.evaluation.test_queue import _answer_rows, _write_answers, _write_sample

BASE = 9_000_000_000
REPO = Path(__file__).resolve().parents[2]


def _configs(tmp_path, status):
    configs = tmp_path / "configs"
    (configs / "questions").mkdir(parents=True)
    (configs / "rubric.v1.md").write_text(
        f"---\nstatus: {status}\nversion: v1\n---\n\n# rubric\n", encoding="utf-8"
    )
    (configs / "acquisition.toml").write_text(
        'snapshot_id = "snap-test"\n', encoding="utf-8"
    )
    shutil.copy(
        REPO / "configs" / "questions" / "screen.v0.json",
        configs / "questions" / "screen.v0.json",
    )
    return configs


def _world(tmp_path, monkeypatch, status):
    monkeypatch.setattr(paths, "LABELS", tmp_path / "labels")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CONFIGS", _configs(tmp_path, status))
    ids = [BASE + i for i in range(600)]
    _write_sample("s1", ids, [1.0] * 600)
    _write_answers("r1", 0, _answer_rows(ids, [i / 600 for i in range(600)]))
    return tmp_path / "labels" / "queues" / "calibration.json"


def _parse(*argv):
    return atlas.cli.build_parser().parse_args(list(argv))


def test_label_run_refuses_draft_rubric(tmp_path, monkeypatch, capsys):
    qpath = _world(tmp_path, monkeypatch, "draft")
    args = _parse(
        "label", "run", "--label-set", "calibration", "--sample", "s1",
        "--run", "r1", "--snapshot", "snap-test", "--no-launch",
    )
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "not approved" in err and "draft" in err
    assert not qpath.exists()


def test_label_run_builds_reuses_and_tops_up(tmp_path, monkeypatch):
    qpath = _world(tmp_path, monkeypatch, "approved")
    args = _parse(
        "label", "run", "--label-set", "calibration", "--sample", "s1",
        "--run", "r1", "--snapshot", "snap-test", "--no-launch",
    )
    args.func(args)
    q = json.loads(qpath.read_text())
    assert len(q["ids"]) == 150
    assert set(q["bands"]) == {"high", "mid", "low"}
    assert q["rates"]["high"] == pytest.approx(60 / 300)
    assert q["rates"]["mid"] == pytest.approx(50 / 210)
    assert q["rates"]["low"] == pytest.approx(40 / 90)
    assert len(q["repeats"]) == 15
    assert len(q["domain_ids"]) == 50 and set(q["domain_ids"]) <= set(q["ids"])
    assert q["label_set"] == "calibration" and q["run_id"] == "r1"
    assert q["sample_id"] == "s1" and q["snapshot_id"] == "snap-test"
    assert q["question_id"] == "firsthand_problem" and q["top_ups"] == []

    args.func(args)  # second run reuses, never redraws
    assert json.loads(qpath.read_text())["ids"] == q["ids"]

    top = _parse(
        "label", "run", "--label-set", "calibration", "--sample", "s1",
        "--run", "r1", "--snapshot", "snap-test", "--no-launch", "--top-up", "50",
    )
    top.func(top)
    q2 = json.loads(qpath.read_text())
    assert len(q2["ids"]) == 200 and len(set(q2["ids"])) == 200
    new = set(q2["ids"]) - set(q["ids"])
    assert len(new) == 50
    scores = {BASE + i: i / 600 for i in range(600)}
    assert all(scores[c] >= 0.15 for c in new)  # high and mid bands only
    assert len(q2["top_ups"]) == 1 and q2["top_ups"][0]["n"] == 50

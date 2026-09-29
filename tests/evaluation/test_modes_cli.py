"""Task 16.4: label run builds/reuses the audit queues; eval reports on them."""

import itertools
import json

import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.cli import build_parser
from atlas.evaluation import audit_queues
from atlas.evaluation.queue import load_queue, queue_path
from atlas.evaluation.store import LabelStore, labels_path, repeats_path
from tests.evaluation.test_modes_support import (
    BASE,
    assignment_world,
    make_env,
    metrics_table,
    write_answers,
    write_merge_cardset,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def _run_cli(*argv):
    args = build_parser().parse_args(list(argv))
    args.func(args)


def _label_run(*argv):
    _run_cli("label", "run", *argv, "--no-launch")


def test_label_run_builds_facet_queue(env, capsys):
    ids = [BASE + i for i in range(100)]
    for part, q in enumerate(audit_queues.FACET_QUESTIONS):
        write_answers(
            "frun", part, ids, [0.9] * 50 + [0.1] * 50, question_id=q
        )
    _label_run(
        "--label-set", "facet_audit", "--run", "frun", "--n", "40",
        "--seed", "3",
    )
    assert "queue facet_audit: 40 ids" in capsys.readouterr().out
    queue = load_queue(queue_path("facet_audit"))
    assert len(queue["ids"]) == 40 and queue["snapshot_id"] == "snap-test"

    _label_run("--label-set", "facet_audit", "--run", "frun")
    assert "reusing queue" in capsys.readouterr().out
    assert load_queue(queue_path("facet_audit"))["ids"] == queue["ids"]


def test_label_run_builds_assignment_queue(env, capsys):
    assignment_world("arun")
    _label_run(
        "--label-set", "assignment_audit", "--run", "arun",
        "--cardset", "synth", "--version", "t9", "--n", "60",
    )
    assert "queue assignment_audit: 60 ids" in capsys.readouterr().out
    assert len(load_queue(queue_path("assignment_audit"))["ids"]) == 60


def test_assignment_queue_requires_cardset_and_version(env, capsys):
    assignment_world("arun")
    capsys.readouterr()
    with pytest.raises(SystemExit):
        _label_run(
            "--label-set", "assignment_audit", "--run", "arun",
            "--version", "t9",
        )
    assert "--cardset" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _label_run(
            "--label-set", "assignment_audit", "--run", "arun",
            "--cardset", "synth",
        )
    assert "--version" in capsys.readouterr().err


def test_label_run_builds_merge_queue(env, capsys):
    write_merge_cardset(env)
    cards = [f"c{i:04d}" for i in range(1, 15)]
    pairs = list(itertools.combinations(cards, 2))[:90]
    expected = [1.9] * 30 + [1.0] * 30 + [0.2] * 30
    scored = [
        {"card_a": a, "card_b": b, "expected": e}
        for (a, b), e in zip(pairs, expected, strict=True)
    ]
    run_dir = paths.run_dir("mrun")
    run_dir.mkdir(parents=True)
    (run_dir / "merge-t9.json").write_text(json.dumps({"scored": scored}))
    _label_run(
        "--label-set", "merge_audit", "--run", "mrun",
        "--cardset", "mergey", "--version", "t9",
    )
    assert "queue merge_audit: 50 ids" in capsys.readouterr().out


def test_label_run_builds_interview_queue(env, capsys):
    assignment_world("arun")
    mpath = env / "metrics.parquet"
    pq.write_table(metrics_table(), mpath)
    _label_run(
        "--label-set", "interview", "--run", "arun",
        "--cardset", "synth", "--version", "t9",
        "--metrics", str(mpath), "--n", "3",
    )
    assert "queue interview: 3 ids" in capsys.readouterr().out
    queue = load_queue(queue_path("interview"))
    assert len(queue["ids"]) == 3
    first = queue["items"][str(queue["ids"][0])]
    assert first["examples"]  # examples joined from the assignments run


def test_interview_queue_requires_metrics(env, capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit):
        _label_run(
            "--label-set", "interview", "--run", "arun",
            "--cardset", "synth", "--version", "t9",
        )
    assert "--metrics" in capsys.readouterr().err


def test_top_up_rejected_for_mode_sets(env, capsys):
    _label_run(
        "--label-set", "facet_audit", "--run", "frun", "--n", "10",
    )
    capsys.readouterr()
    with pytest.raises(SystemExit):
        _label_run(
            "--label-set", "facet_audit", "--run", "frun", "--top-up", "5",
        )


def test_calibration_requires_sample(env, capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit):
        _label_run("--label-set", "calibration", "--run", "frun")
    assert "--sample" in capsys.readouterr().err


def _label(queue, label_set, question_id, by_id, store=None):
    store = store or LabelStore(labels_path())
    for cid in queue["ids"]:
        store.add(
            comment_id=cid,
            label_set=label_set,
            question_id=question_id,
            value=by_id(cid),
            rubric_version="v1",
            reviewer="test",
            started_at="t0",
            ended_at="t1",
            seconds=1.0,
        )


def test_eval_assignment_audit(env, capsys):
    assignment_world("arun")
    _label_run(
        "--label-set", "assignment_audit", "--run", "arun",
        "--cardset", "synth", "--version", "t9", "--n", "60",
    )
    capsys.readouterr()
    queue = load_queue(queue_path("assignment_audit"))
    blind = queue["hidden"]
    _label(
        queue, "assignment_audit", "fits",
        lambda cid: "yes" if blind[str(cid)]["is_jev"] else "no",
    )
    rep = queue["repeats"][0]
    LabelStore(repeats_path()).add(
        comment_id=rep,
        label_set="assignment_audit",
        question_id="fits",
        value="yes" if blind[str(rep)]["is_jev"] else "no",
        rubric_version="v1",
        reviewer="test",
        started_at="t0",
        ended_at="t1",
        seconds=1.0,
    )

    _run_cli(
        "eval", "run", "--label-set", "assignment_audit",
        "--run", "arun", "--n-boot", "100",
    )
    out = paths.run_dir("arun") / "eval_assignment_audit.json"
    assert out.exists()
    report = json.loads(out.read_text())
    jev = report["groups"]["jev"]
    assert jev["lenient"]["precision"] == 1.0
    assert jev["strict"]["precision"] == 1.0
    assert report["groups"]["random"]["lenient"]["precision"] == 0.0
    assert report["gap"]["strict"] == 1.0
    assert report["agreement"]["fits"] == {"n": 1, "agreement": 1.0}
    assert report["meets_target"]["lenient"] is True
    assert report["queue_run_id"] == "arun"
    assert "warning" not in report


def test_eval_facet_audit(env, capsys):
    run_id = "frun"
    ids = [BASE + i for i in range(200)]
    nouls = [0.9] * 100 + [0.1] * 100
    for part, q in enumerate(audit_queues.FACET_QUESTIONS):
        write_answers(run_id, part, ids, nouls, question_id=q)
    _label_run("--label-set", "facet_audit", "--run", run_id, "--n", "60")
    capsys.readouterr()
    queue = load_queue(queue_path("facet_audit"))
    high = set(queue["bands"]["high"]["ids"])
    store = LabelStore(labels_path())
    for q in audit_queues.FACET_QUESTIONS:
        _label(
            queue, "facet_audit", q,
            lambda cid: "yes" if cid in high else "no",
            store=store,
        )

    _run_cli(
        "eval", "run", "--label-set", "facet_audit",
        "--run", run_id, "--n-boot", "100",
    )
    out = paths.run_dir(run_id) / "eval_facet_audit.json"
    assert out.exists()
    report = json.loads(out.read_text())
    for q in audit_queues.FACET_QUESTIONS:
        facet = report["facets"][q]
        assert facet["precision"] == 1.0 and facet["recall"] == 1.0
    assert report["resolution"]["n"] == 0


def test_eval_missing_queue_errors(env, capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit):
        _run_cli("eval", "run", "--label-set", "assignment_audit",
                 "--run", "arun")
    assert "assignment_audit" in capsys.readouterr().err

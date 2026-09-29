"""Task 18.4: unblinded comments and void labels are excluded everywhere."""

import json
import sys
import types

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.evaluation import audit_eval, exclusions
from atlas.evaluation.cli import evaluate
from atlas.evaluation.queue import queue_path, save_queue
from atlas.evaluation.store import labels_path

BASE = 9_000_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LABELS", tmp_path / "labels")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    return tmp_path


def _label(label_id, comment_id, label_set="calibration",
           question_id="firsthand_problem", value="yes"):
    return {
        "label_id": label_id,
        "comment_id": comment_id,
        "label_set": label_set,
        "question_id": question_id,
        "value": value,
        "rubric_version": "v1",
        "reviewer": "test",
        "started_at": "t0",
        "ended_at": "t1",
        "seconds": 1.0,
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_missing_files_give_empty_exclusions(env):
    assert exclusions.excluded_comment_ids() == {}
    assert exclusions.excluded_label_ids() == {}
    assert exclusions.excluded_label_ids("calibration") == {}


def test_unblinded_and_void_files(env):
    _write_json(paths.LABELS / "unblinded.json", {
        "reason": "answers shown before labeling",
        "comment_ids": [BASE + 1, BASE + 2],
        "recorded_at": "2026-09-29T00:00:00Z",
    })
    _write_json(paths.LABELS / "void_calibration.json", {
        "reason": "saved by a ui bug",
        "label_set": "calibration",
        "label_ids": ["aa" * 16],
    })
    _write_json(paths.LABELS / "void_heldout.json", {
        "reason": "double saved",
        "label_set": "heldout",
        "label_ids": ["bb" * 16],
    })
    _write_json(paths.LABELS / "void_legacy.json", {
        "reason": "voided before label sets existed",
        "label_ids": ["cc" * 16],
    })
    assert exclusions.excluded_comment_ids() == {
        BASE + 1: "answers shown before labeling",
        BASE + 2: "answers shown before labeling",
    }
    assert exclusions.excluded_label_ids("calibration") == {
        "aa" * 16: "saved by a ui bug",
        "cc" * 16: "voided before label sets existed",
    }
    assert exclusions.excluded_label_ids("heldout") == {
        "bb" * 16: "double saved",
        "cc" * 16: "voided before label sets existed",
    }
    assert exclusions.excluded_label_ids() == {
        "aa" * 16: "saved by a ui bug",
        "bb" * 16: "double saved",
        "cc" * 16: "voided before label sets existed",
    }


def test_latest_drops_voided_row_and_keeps_earlier(env):
    _write_jsonl(labels_path(), [
        _label("aa" * 16, BASE + 1, value="yes"),
        _label("bb" * 16, BASE + 1, value="no"),  # later correction, voided
        _label("cc" * 16, BASE + 2, value="no"),  # unblinded comment
        _label("dd" * 16, BASE + 3, value="yes", label_set="heldout"),
    ])
    _write_json(paths.LABELS / "unblinded.json", {
        "reason": "answers shown before labeling",
        "comment_ids": [BASE + 2],
        "recorded_at": "2026-09-29T00:00:00Z",
    })
    _write_json(paths.LABELS / "void_calibration.json", {
        "reason": "saved by a ui bug",
        "label_set": "calibration",
        "label_ids": ["bb" * 16],
    })
    latest, meta = exclusions.latest(labels_path(), "calibration")
    assert set(latest) == {(BASE + 1, "firsthand_problem")}
    assert latest[(BASE + 1, "firsthand_problem")]["value"] == "yes"
    assert meta["n_excluded"] == 2
    assert meta["excluded_reasons"] == {
        "answers shown before labeling": 1,
        "saved by a ui bug": 1,
    }


def test_assignment_audit_drops_void_label(env):
    queue = {
        "label_set": "assignment_audit",
        "run_id": "arun",
        "ids": [BASE, BASE + 1],
        "bands": {},
        "rates": {},
        "items": {},
        "hidden": {
            str(BASE): {"is_jev": True, "forced": False},
            str(BASE + 1): {"is_jev": False, "forced": False},
        },
        "repeats": [],
    }
    save_queue(queue, queue_path("assignment_audit"))
    _write_jsonl(labels_path(), [
        _label("aa" * 16, BASE, label_set="assignment_audit",
               question_id="fits", value="yes"),
        _label("bb" * 16, BASE + 1, label_set="assignment_audit",
               question_id="fits", value="no"),
    ])
    _write_json(paths.LABELS / "void_assignment_audit.json", {
        "reason": "saved by a ui bug",
        "label_set": "assignment_audit",
        "label_ids": ["bb" * 16],
    })
    report = audit_eval.evaluate_assignment_audit("arun", n_boot=10, seed=0)
    assert report["n_excluded"] == 1
    assert report["excluded_reasons"] == {"saved by a ui bug": 1}
    assert report["groups"]["jev"]["n"] == 1
    assert report["groups"]["random"]["n"] == 0


def test_evaluate_drops_unblinded_comment(env, monkeypatch):
    n = 20
    ids = [BASE + i for i in range(n)]
    _write_jsonl(labels_path(), [
        _label(f"{i:032x}", cid, value="yes" if i % 2 else "no")
        for i, cid in enumerate(ids)
    ])
    rows = [
        {
            "run_id": "r1", "comment_id": cid, "question_set": "screen@1",
            "question_id": "firsthand_problem", "qtype": "noul",
            "noul": 0.9 if i % 2 else 0.1, "choice": None, "score": None,
            "probabilities_json": None, "confidence": None,
            "model_returned": "m", "request_id": "req",
            "logical_call_id": f"lc-{cid}", "cache_hit": False,
        }
        for i, cid in enumerate(ids)
    ]
    directory = paths.run_dir("r1") / "answers"
    directory.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=contracts.ANSWERS),
                   directory / "part-0.parquet")
    _write_json(paths.LABELS / "unblinded.json", {
        "reason": "answers shown before labeling",
        "comment_ids": [ids[0]],
        "recorded_at": "t",
    })
    items = types.ModuleType("atlas.sources.items")
    items.load_items = lambda snapshot_dir, cids: [
        {"comment_id": c, "comment": "synthetic text"} for c in cids]
    monkeypatch.setitem(sys.modules, "atlas.sources.items", items)
    report = evaluate("calibration", "r1", n_boot=20, seed=0)
    assert report["n_labeled"] == n - 1
    assert report["n_excluded"] == 1
    assert report["excluded_reasons"] == {"answers shown before labeling": 1}

"""L22 22.3a: `pilot packed-cal` — packed screen over calibration-queue
comments the packed experiment has not covered (run ``<pilot>-packedcal``).
"""

import json

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.pilot import packed, stages
from atlas.pilot.draw import pilot_draw
from atlas.pilot.packed_cal import run_packed_cal
from tests.pilot.test_support import (  # noqa: F401
    SNAPSHOT_ID,
    make_transport,
    mock_env,
    pilot_repo,
)

RUN = "pilot-7"
SAMPLE = "pilot-7"
CAL_RUN = "pilot-7-packedcal"


def _write_queue(ids) -> None:
    qdir = paths.LABELS / "queues"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "calibration.json").write_text(
        json.dumps({"ids": [int(i) for i in ids], "seed": 1}) + "\n"
    )


def _write_packed_map(run_id, ids) -> None:
    d = paths.run_dir(f"{run_id}-packed")
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"packed_id": int(c), "slot": "c1", "comment_id": int(c)}
                for c in ids
            ],
            schema=packed.PACKED_MAP,
        ),
        d / "packed_map.parquet",
    )


def _screened(monkeypatch):
    table = pilot_draw(SNAPSHOT_ID, n_target=60, min_per_stratum=10, seed=7)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    stages.run_screen(SAMPLE, RUN, yes=True)
    ids = sorted(int(c) for c in table.column("comment_id").to_pylist())
    return seen, ids


def test_packed_cal_dry_run(pilot_repo, monkeypatch, capsys):  # noqa: F811
    seen, ids = _screened(monkeypatch)
    n_screen = len(seen)
    cal, already = ids[:8], ids[:3]
    _write_queue(cal)
    _write_packed_map(RUN, already)

    out = run_packed_cal(RUN, k=5)
    assert out["dispatched"] is False
    assert out["todo"] == 5
    assert out["calibration_ids"] == 8
    assert out["already_packed"] == 3
    assert out["estimate"]["calls"] == 1  # ceil(5 / 5)
    assert out["estimate"]["question_set"] == packed.PACKED_LABEL
    assert len(seen) == n_screen
    assert not paths.run_dir(CAL_RUN).exists()
    printed = capsys.readouterr().out
    assert "calibration ids 8, already packed 3, to pack 5" in printed


def test_packed_cal_end_to_end(pilot_repo, monkeypatch, capsys):  # noqa: F811
    seen, ids = _screened(monkeypatch)
    n_screen = len(seen)
    cal, already = ids[:9], ids[:3]
    _write_queue(cal)
    _write_packed_map(RUN, already)

    out = run_packed_cal(RUN, k=5, yes=True)
    assert out["dispatched"] is True
    todo = cal[3:]
    assert len(seen) - n_screen == 2  # ceil(6 / 5) packed calls
    assert out["estimate"]["calls"] == 2

    run_dir = paths.run_dir(CAL_RUN)
    pmap = pq.read_table(run_dir / "packed_map.parquet")
    # The fixed map is long format: packed_id, slot, comment_id.
    assert pmap.schema == packed.PACKED_MAP
    assert pmap.num_rows == len(todo)
    assert sorted(pmap.column("comment_id").to_pylist()) == todo
    assert pmap.column("slot").to_pylist() == [
        f"c{i % 5 + 1}" for i in range(len(todo))
    ]

    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["budget"] == "pilot"
    assert [e["label"] for e in manifest["question_sets"]] == [
        packed.PACKED_LABEL
    ]

    answers = pq.read_table(run_dir / "answers")
    assert {r["question_set"] for r in answers.to_pylist()} == {
        packed.PACKED_LABEL
    }
    unpacked = packed.unpack_answers(answers, pmap)
    assert sorted(unpacked.column("comment_id").to_pylist()) == todo

    # Rerun resumes via the done set: no new requests.
    again = run_packed_cal(RUN, k=5, yes=True)
    assert again["run"]["new_requests"] == 0
    assert again["run"]["skipped_completed"] == 2


def test_packed_cal_without_prior_packed_run(pilot_repo, monkeypatch, capsys):  # noqa: F811
    _seen, ids = _screened(monkeypatch)
    _write_queue(ids[:6])
    out = run_packed_cal(RUN, k=5, yes=True)
    assert out["dispatched"] is True
    pmap = pq.read_table(paths.run_dir(CAL_RUN) / "packed_map.parquet")
    assert sorted(pmap.column("comment_id").to_pylist()) == ids[:6]

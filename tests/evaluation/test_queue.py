import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.evaluation.queue import (
    build_queue,
    domain_subset,
    labeling_frame,
    load_queue,
    queue_path,
    read_answers,
    save_queue,
    sequence,
    top_up,
)

BASE = 9_000_000_000


def _frame(n, scores=None):
    cols = {"comment_id": list(range(BASE, BASE + n))}
    if scores is not None:
        cols["score"] = scores
    return pa.table(cols)


def test_queue_is_seeded_and_excludes_ids():
    frame = pa.table({"comment_id": list(range(BASE, BASE + 100)), "stratum": ["A"] * 100})
    q1 = build_queue(frame, n=10, seed=3, exclude={BASE, BASE + 1, BASE + 2})
    q2 = build_queue(frame, n=10, seed=3, exclude={BASE, BASE + 1, BASE + 2})
    assert q1 == q2 and len(q1["ids"]) == 10
    assert not ({BASE, BASE + 1, BASE + 2} & set(q1["ids"]))


def test_band_queue_records_rates_and_repeats():
    scores = [i / 1000 for i in range(1000)]
    frame = pa.table({"comment_id": list(range(BASE, BASE + 1000)), "score": scores})
    q = build_queue(frame, n=None, seed=2, bands={"high": (0.5, 1.01), "low": (0, 0.5)},
                    band_sizes={"high": 10, "low": 10})
    assert len(q["ids"]) == 20 and q["rates"] == {"high": 10 / 500, "low": 10 / 500}
    assert len(q["repeats"]) == 2 and set(q["repeats"]) <= set(q["ids"])


def test_banded_ids_not_clustered_by_band():
    scores = [i / 1000 for i in range(1000)]
    frame = pa.table({"comment_id": list(range(BASE, BASE + 1000)), "score": scores})
    q = build_queue(frame, n=None, seed=2, bands={"high": (0.5, 1.01), "low": (0, 0.5)},
                    band_sizes={"high": 10, "low": 10})
    high_ids = set(q["bands"]["high"]["ids"])
    high_positions = [i for i, cid in enumerate(q["ids"]) if cid in high_ids]
    assert high_positions != list(range(len(high_ids)))
    low_ids = set(q["bands"]["low"]["ids"])
    low_positions = [i for i, cid in enumerate(q["ids"]) if cid in low_ids]
    assert low_positions != list(range(len(q["ids"]) - len(low_ids), len(q["ids"])))


def test_top_up_draws_more_from_named_bands():
    scores = [i / 1000 for i in range(1000)]
    frame = pa.table({"comment_id": list(range(BASE, BASE + 1000)), "score": scores})
    bands = {"high": (0.5, 1.01), "mid": (0.15, 0.5), "low": (0.0, 0.15)}
    q = build_queue(frame, n=None, seed=2, bands=bands,
                    band_sizes={"high": 10, "mid": 10, "low": 5})
    q["top_ups"] = []
    q2 = top_up(q, frame, 20)
    assert len(q["ids"]) == 25  # input unchanged
    new = set(q2["ids"]) - set(q["ids"])
    assert len(new) == 20
    sc = dict(zip(frame["comment_id"].to_pylist(), frame["score"].to_pylist(), strict=True))
    assert all(sc[c] >= 0.15 for c in new)  # high and mid only
    assert len(q2["ids"]) == len(set(q2["ids"]))
    assert q2["rates"]["high"] == len(q2["bands"]["high"]["ids"]) / q2["bands"]["high"]["count"]
    assert q2["rates"]["mid"] == len(q2["bands"]["mid"]["ids"]) / q2["bands"]["mid"]["count"]
    assert q2["rates"]["low"] == q["rates"]["low"]  # untouched band unchanged
    assert len(q2["repeats"]) == len(q["repeats"]) + 2
    assert set(q2["repeats"]) - set(q["repeats"]) <= new
    assert len(q2["top_ups"]) == 1 and q2["top_ups"][0]["n"] == 20
    assert top_up(q, frame, 20) == q2  # deterministic


def test_sequence_appends_repeats():
    q = {"ids": [BASE + 1, BASE + 2], "repeats": [BASE + 1]}
    assert sequence(q) == [(BASE + 1, False), (BASE + 2, False), (BASE + 1, True)]


def test_domain_subset(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LABELS", tmp_path / "labels")
    ids = list(range(BASE, BASE + 200))
    sub = domain_subset(ids, seed=1)
    assert len(sub) == 50 and set(sub) <= set(ids) and len(set(sub)) == 50
    assert domain_subset(ids, seed=1) == sub
    q = {"ids": ids[:10], "repeats": [], "seed": 1}
    p = queue_path("heldout")
    save_queue(q, p)
    assert p == tmp_path / "labels" / "queues" / "heldout.json"
    assert load_queue(p) == q


def _write_sample(sample_id, ids, weights):
    table = pa.table(
        {
            "sample_id": [sample_id] * len(ids),
            "comment_id": ids,
            "story_id": [BASE + 100] * len(ids),
            "stratum": ["P01"] * len(ids),
            "inclusion_prob": [0.5] * len(ids),
            "weight": weights,
            "batch": [1] * len(ids),
            "draw_order": list(range(len(ids))),
        },
        schema=contracts.SAMPLE,
    )
    path = paths.sample_path(sample_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _write_answers(run_id, part, rows):
    directory = paths.run_dir(run_id) / "answers"
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.table(rows, schema=contracts.ANSWERS)
    pq.write_table(table, directory / f"part-{part}.parquet")


def _answer_rows(ids, nouls):
    n = len(ids)
    return {
        "run_id": ["r1"] * n,
        "comment_id": ids,
        "question_set": ["screen@0"] * n,
        "question_id": ["firsthand_problem"] * n,
        "qtype": ["noul"] * n,
        "noul": nouls,
        "choice": [None] * n,
        "score": [None] * n,
        "probabilities_json": [None] * n,
        "confidence": [None] * n,
        "model_returned": ["m-test"] * n,
        "request_id": ["req"] * n,
        "logical_call_id": ["lc"] * n,
        "cache_hit": [False] * n,
    }


def test_labeling_frame_and_read_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    ids = [BASE + i for i in range(5)]
    _write_sample("s1", ids, [2.0] * 5)
    _write_answers("r1", 0, _answer_rows(ids, [0.1, 0.5, None, 0.9, 0.3]))
    # A later row wins; a second question is ignored by the filter.
    _write_answers("r1", 1, _answer_rows([ids[1]], [0.77]))
    extra = _answer_rows([ids[0]], [None])
    extra["question_id"] = ["account_type"]
    extra["qtype"] = ["choice"]
    extra["choice"] = ["firsthand_account"]
    _write_answers("r1", 2, extra)

    answers = read_answers("r1", "firsthand_problem")
    assert answers[ids[1]]["noul"] == 0.77
    assert answers[ids[0]] == {"noul": 0.1, "choice": None}
    assert read_answers("no-such-run", "firsthand_problem") == {}

    frame = labeling_frame("s1", "r1")
    assert frame.schema.names == ["comment_id", "score", "weight"]
    got = dict(zip(
        frame["comment_id"].to_pylist(), frame["score"].to_pylist(), strict=True
    ))
    assert ids[2] not in got  # null noul dropped
    assert len(frame) == 4 and got[ids[1]] == 0.77
    weights = dict(zip(
        frame["comment_id"].to_pylist(), frame["weight"].to_pylist(), strict=True
    ))
    assert weights[ids[0]] == 2.0

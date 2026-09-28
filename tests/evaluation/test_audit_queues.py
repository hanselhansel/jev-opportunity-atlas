"""Task 16.2: audit queue builders write blinded queues and GOLD_DRAWS rows."""

import itertools

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from atlas import contracts, paths
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.merge import pair_id
from atlas.evaluation import audit_queues
from atlas.evaluation.queue import load_queue, queue_path

BASE = 9_000_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    cards_dir = configs / "cards"
    cards_dir.mkdir(parents=True)
    cardset = {
        "taxonomy_version": "t9",
        "groups": {
            "g01": {"label": "Synthetic group one"},
            "g02": {"label": "Synthetic group two"},
        },
        "cards": [
            {"card_id": "c0001", "group_id": "g01",
             "statement": "Synthetic need alpha", "status": "approved"},
            {"card_id": "c0002", "group_id": "g01",
             "statement": "Synthetic need beta", "status": "approved"},
            {"card_id": "c0003", "group_id": "g01",
             "statement": "Synthetic need gamma", "status": "approved"},
            {"card_id": "c0004", "group_id": "g01",
             "statement": "Synthetic need delta", "status": "approved"},
            {"card_id": "c0005", "group_id": "g02",
             "statement": "Synthetic need solo", "status": "approved"},
            {"card_id": "c0006", "group_id": "g01",
             "statement": "Synthetic need retired", "status": "retired"},
        ],
    }
    (cards_dir / "synth.t9.yaml").write_text(yaml.safe_dump(cardset))
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "LABELS", tmp_path / "labels")
    monkeypatch.setattr(paths, "CONFIGS", configs)
    return tmp_path


def _answers(run_id, part, comment_ids, nouls,
             question_id="workaround", question_set="facets@1"):
    n = len(comment_ids)
    rows = {
        "run_id": [run_id] * n,
        "comment_id": comment_ids,
        "question_set": [question_set] * n,
        "question_id": [question_id] * n,
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
    directory = paths.run_dir(run_id) / "answers"
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(rows, schema=contracts.ANSWERS),
        directory / f"part-{part}.parquet",
    )


def _write_assignments(run_id, version, rows):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ASSIGNMENTS),
        run_dir / f"assignments-{version}.parquet",
    )


def _write_pain(run_id, pairs):
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [{"comment_id": c, "pain_sentence": t} for c, t in pairs],
            schema=pa.schema(
                [("comment_id", pa.int64()), ("pain_sentence", pa.string())]
            ),
        ),
        run_dir / "pain.parquet",
    )


def _gold_rows():
    return pq.read_table(paths.LABELS / "gold_draws.parquet").to_pylist()


def test_facet_audit_queue(env):
    run_id = "frun"
    high = [BASE + i for i in range(200)]
    low = [BASE + 200 + i for i in range(200)]
    _answers(run_id, 0, high, [0.9] * 200)
    _answers(run_id, 1, low, [0.1] * 200)
    # A second facet row: max over facets, and nulls are ignored.
    _answers(run_id, 2, high, [0.4] * 200, question_id="paid")
    _answers(run_id, 3, low, [None] * 200, question_id="paid")
    # Null-only comments are not candidates; other sets are ignored.
    _answers(run_id, 4, [BASE + 500 + i for i in range(5)], [None] * 5)
    _answers(run_id, 5, [BASE + 600], [0.9], question_set="screen@0")

    gpath = paths.LABELS / "gold_draws.parquet"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    prior = {
        "label_set": "calibration",
        "comment_id": BASE + 999,
        "draw_stratum": "high",
        "selection_prob": 0.5,
        "seed": 0,
        "purpose": "calibration",
    }
    pq.write_table(
        pa.Table.from_pylist([prior], schema=contracts.GOLD_DRAWS), gpath
    )

    q = audit_queues.facet_audit_queue(run_id, seed=1, snapshot_id="snap-1")
    assert q["label_set"] == "facet_audit"
    assert q["run_id"] == run_id
    assert q["snapshot_id"] == "snap-1"
    assert q["question_set"] == "facets@1"
    assert len(q["ids"]) == 150
    assert len(q["bands"]["high"]["ids"]) == 75
    assert len(q["bands"]["low"]["ids"]) == 75
    assert q["rates"] == {"high": 75 / 200, "low": 75 / 200}
    assert len(q["repeats"]) == 15 and set(q["repeats"]) <= set(q["ids"])
    assert set(q["items"]) == {str(c) for c in q["ids"]}
    assert all(set(item) == {"comment_id"} for item in q["items"].values())
    assert q["hidden"] == {}
    assert load_queue(queue_path("facet_audit"))["ids"] == q["ids"]

    again = audit_queues.facet_audit_queue(run_id, seed=1)
    assert again["ids"] == q["ids"] and again["repeats"] == q["repeats"]

    rows = _gold_rows()
    assert [r for r in rows if r["label_set"] == "calibration"] == [prior]
    gold = [r for r in rows if r["label_set"] == "facet_audit"]
    assert len(gold) == 150
    band_of = {
        c: b for b, info in q["bands"].items() for c in info["ids"]
    }
    for r in gold:
        assert r["purpose"] == "audit" and r["seed"] == 1
        assert r["draw_stratum"] == band_of[r["comment_id"]]
        assert r["selection_prob"] == pytest.approx(
            q["rates"][r["draw_stratum"]]
        )


def _assignment_row(cid, group, card, card_confidence):
    return {
        "run_id": "arun",
        "comment_id": cid,
        "taxonomy_version": "t9",
        "group_id": group,
        "group_p": 0.9,
        "group_confidence": 0.9,
        "card_id": card,
        "card_p": 0.8 if card not in (None, "none") else None,
        "card_confidence": card_confidence,
        "verified_p": None,
    }


def test_assignment_audit_queue(env):
    run_id = "arun"
    rows = []
    cards = ["c0001", "c0002", "c0003", "c0004"]
    for i in range(300):  # g01: 150 high-confidence, 150 low
        rows.append(_assignment_row(
            BASE + i, "g01", cards[i % 4], 0.9 if i < 150 else 0.2
        ))
    for i in range(300):  # g02: one active card only, both bands
        rows.append(_assignment_row(
            BASE + 300 + i, "g02", "c0005", 0.85 if i < 150 else 0.25
        ))
    junk_ids = [BASE + 600 + i for i in range(6)]
    rows += [
        _assignment_row(junk_ids[0], "g01", "none", 0.9),
        _assignment_row(junk_ids[1], "none", None, None),
        _assignment_row(junk_ids[2], "g01", "c0006", 0.9),   # retired card
        _assignment_row(junk_ids[3], "g01", "c0001", None),  # no confidence
        _assignment_row(junk_ids[4], "g01", "c0099", 0.9),   # unknown card
        _assignment_row(junk_ids[5], "g01", "c0001", 0.9),   # no pain text
    ]
    _write_assignments(run_id, "t9", rows)
    pain = {
        c: f"synthetic pain sentence for {c}"
        for c in list(range(BASE, BASE + 600)) + junk_ids[:5]
    }
    _write_pain(run_id, sorted(pain.items()))

    q = audit_queues.assignment_audit_queue(run_id, "t9", seed=1, cardset="synth")
    cs = load_cardset("synth", "t9")
    assert q["label_set"] == "assignment_audit"
    assert q["run_id"] == run_id
    assert q["taxonomy_version"] == "t9" and q["cardset"] == "synth"
    assert q["seed"] == 1 and q["show_seed"] == 17 and q["show_prob"] == 0.5
    assert len(q["ids"]) == 200
    assert len(q["bands"]["high"]["ids"]) == 100
    assert len(q["bands"]["low"]["ids"]) == 100
    assert len(q["repeats"]) == 20 and set(q["repeats"]) <= set(q["ids"])
    assert set(q["ids"]).isdisjoint(junk_ids)
    assert set(q["items"]) == set(q["hidden"]) == {
        str(c) for c in q["ids"]
    }

    for cid in q["ids"]:
        item = q["items"][str(cid)]
        assert set(item) == {"comment_id", "pain_sentence", "card_statement"}
        assert item["comment_id"] == cid
        assert item["pain_sentence"] == pain[cid]
        hid = q["hidden"][str(cid)]
        assert set(hid) == {
            "jev_card_id",
            "shown_card_id",
            "is_jev",
            "forced",
        }
        jev = cs.cards[hid["jev_card_id"]]
        shown = cs.cards[hid["shown_card_id"]]
        assert shown.group_id == jev.group_id
        assert item["card_statement"] == shown.statement
        assert hid["is_jev"] == (hid["shown_card_id"] == hid["jev_card_id"])

    g02 = [
        h for h in q["hidden"].values()
        if cs.cards[h["jev_card_id"]].group_id == "g02"
    ]
    assert g02 and all(h["forced"] and h["is_jev"] for h in g02)
    non_forced = [h for h in q["hidden"].values() if not h["forced"]]
    share = sum(h["is_jev"] for h in non_forced) / len(non_forced)
    assert 0.35 <= share <= 0.65

    gold = [r for r in _gold_rows() if r["label_set"] == "assignment_audit"]
    assert len(gold) == 200
    band_of = {
        c: b for b, info in q["bands"].items() for c in info["ids"]
    }
    for r in gold:
        assert r["purpose"] == "audit"
        assert r["selection_prob"] == pytest.approx(
            q["rates"][band_of[r["comment_id"]]]
        )


def _merge_cardset(env):
    data = {
        "taxonomy_version": "t9",
        "groups": {"g01": {"label": "Merge group"}},
        "cards": [
            {"card_id": f"c{i:04d}", "group_id": "g01",
             "statement": f"Synthetic merge need {i}", "status": "approved"}
            for i in range(1, 15)
        ],
    }
    (env / "configs" / "cards" / "mergey.t9.yaml").write_text(
        yaml.safe_dump(data)
    )


def test_merge_audit_queue(env):
    _merge_cardset(env)
    cs = load_cardset("mergey", "t9")
    cards = [f"c{i:04d}" for i in range(1, 15)]
    pairs = list(itertools.combinations(cards, 2))[:90]
    expected = [1.9] * 30 + [1.0] * 30 + [0.2] * 30
    scored = [
        {"card_a": a, "card_b": b, "expected": e}
        for (a, b), e in zip(pairs, expected, strict=True)
    ]

    q = audit_queues.merge_audit_queue(
        scored, seed=1, taxonomy_version="t9", cardset="mergey"
    )
    assert q["label_set"] == "merge_audit"
    assert q["taxonomy_version"] == "t9" and q["cardset"] == "mergey"
    assert len(q["ids"]) == 50
    assert q["repeats"] == []
    sizes = {b: len(info["ids"]) for b, info in q["bands"].items()}
    assert sizes == {"same": 17, "related": 17, "different": 16}

    by_id = {
        pair_id("t9", a, b): (a, b, e)
        for (a, b), e in zip(pairs, expected, strict=True)
    }
    assert set(q["ids"]) <= set(by_id)
    for cid in q["ids"]:
        a, b, e = by_id[cid]
        assert q["items"][str(cid)] == {
            "card_a": cs.all_cards[a].statement,
            "card_b": cs.all_cards[b].statement,
        }
        assert q["hidden"][str(cid)] == {
            "card_a": a,
            "card_b": b,
            "expected": e,
        }

    gold = [r for r in _gold_rows() if r["label_set"] == "merge_audit"]
    assert len(gold) == 50
    band_of = {
        c: b for b, info in q["bands"].items() for c in info["ids"]
    }
    for r in gold:
        assert r["purpose"] == "audit" and r["seed"] == 1
        assert r["draw_stratum"] == band_of[r["comment_id"]]
        assert r["selection_prob"] == pytest.approx(
            q["rates"][r["draw_stratum"]]
        )


def _metrics(with_score=True):
    cols = {
        "card_id": ["c0001", "c0002", "c0003", "c0004", "c0005",
                    "c0006", "c0099"],
        "n_authors": [10, 20, 30, 40, 50, 60, 70],
        "n_threads": [1, 2, 3, 4, 5, 6, 7],
        "n_periods": [1, 1, 2, 2, 3, 3, 4],
        "n_domains": [1, 2, 1, 2, 1, 2, 1],
    }
    if with_score:
        cols["score"] = [0.9, 0.7, 0.8, 0.6, 0.5, 1.0, 0.95]
    return pa.table(cols)


def test_interview_queue(env):
    examples = {"c0001": [f"example sentence {i}" for i in range(7)]}
    q = audit_queues.interview_queue(
        _metrics(), top_k=3, taxonomy_version="t9", cardset="synth",
        examples=examples, seed=5,
    )
    want = [
        audit_queues.card_item_id("t9", c)
        for c in ("c0001", "c0003", "c0002")
    ]
    assert q["ids"] == want  # score desc; retired/unknown cards skipped
    assert q["repeats"] == [] and q["bands"] == {} and q["rates"] == {}
    assert q["seed"] == 5
    assert q["taxonomy_version"] == "t9" and q["cardset"] == "synth"

    item = q["items"][str(want[0])]
    assert item["statement"] == "Synthetic need alpha"
    assert item["group_label"] == "Synthetic group one"
    assert len(item["examples"]) == 5
    assert set(item["examples"]) <= set(examples["c0001"])
    assert item["metrics"] == {
        "authors": 10,
        "threads": 1,
        "periods": 1,
        "domains": 1,
    }
    assert q["hidden"][str(want[0])] == {"card_id": "c0001"}
    item2 = q["items"][str(want[1])]
    assert item2["examples"] == []

    rows = _gold_rows()
    assert len(rows) == 3
    for r in rows:
        assert r["label_set"] == "interview"
        assert r["draw_stratum"] == "top_k"
        assert r["selection_prob"] is None
        assert r["seed"] == 5 and r["purpose"] == "audit"


def test_interview_queue_ranks_by_authors_without_score(env):
    metrics = pa.table({
        "card_id": ["c0001", "c0002", "c0003", "c0004", "c0005"],
        "n_authors": [5, 40, 40, 20, 10],
    })
    q = audit_queues.interview_queue(
        metrics, top_k=2, taxonomy_version="t9", cardset="synth"
    )
    want = [
        audit_queues.card_item_id("t9", c) for c in ("c0002", "c0003")
    ]
    assert q["ids"] == want  # 40 each, ties by card_id ascending
    item = q["items"][str(want[0])]
    assert item["metrics"]["authors"] == 40
    assert item["metrics"]["threads"] is None  # missing column -> None


def test_interview_examples(env):
    run_id = "arun"
    # Low card_p is dropped by the min_card_p filter.
    _write_assignments(run_id, "t9", [
        _assignment_row(BASE, "g01", "c0001", 0.9),
        _assignment_row(BASE + 1, "g01", "c0001", 0.9),
        _assignment_row(BASE + 2, "g01", "c0006", 0.9),
        _assignment_row(BASE + 3, "g01", "none", 0.9),
        _assignment_row(BASE + 4, "g02", "c0005", 0.9),
        {**_assignment_row(BASE + 5, "g01", "c0002", 0.9), "card_p": 0.2},
    ])
    _write_pain(run_id, [
        (BASE, "first synthetic pain"),
        (BASE + 1, "second synthetic pain"),
        (BASE + 2, "retired pain"),
        (BASE + 3, "none pain"),
        (BASE + 4, "solo pain"),
        (BASE + 5, "low confidence pain"),
    ])
    out = audit_queues.interview_examples(run_id, "t9", "synth")
    assert out == {
        "c0001": ["first synthetic pain", "second synthetic pain"],
        "c0005": ["solo pain"],
    }


def test_write_gold_validates(env):
    base = {
        "label_set": "interview",
        "comment_id": BASE,
        "draw_stratum": "top_k",
        "selection_prob": None,
        "seed": 1,
        "purpose": "audit",
    }
    with pytest.raises(ValueError):
        audit_queues.write_gold(
            [dict(base, label_set="facet_audit")], "facet_audit"
        )
    with pytest.raises(ValueError):
        audit_queues.write_gold([dict(base, purpose="estimate")], "interview")
    with pytest.raises(ValueError):
        audit_queues.write_gold(
            [dict(base, purpose="bogus", selection_prob=0.5)], "interview"
        )
    with pytest.raises(ValueError):
        audit_queues.write_gold([dict(base, label_set="audit")], "interview")
    with pytest.raises(ValueError):
        audit_queues.write_gold(
            [dict(base, purpose="calibration", selection_prob=0.0)],
            "interview",
        )
    audit_queues.write_gold([base], "interview")
    rows = _gold_rows()
    assert rows[0]["selection_prob"] is None
    # Only rows of this label set are replaced.
    audit_queues.write_gold(
        [dict(base, comment_id=BASE + 1)], "interview"
    )
    assert [r["comment_id"] for r in _gold_rows()] == [BASE + 1]

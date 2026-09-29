"""Task 16.2: audit queue builders write blinded queues and GOLD_DRAWS rows."""

import itertools

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.merge import pair_id
from atlas.evaluation import audit_queues
from atlas.evaluation.queue import load_queue, queue_path
from tests.evaluation.test_modes_support import (
    BASE,
    assignment_row,
    assignment_world,
    gold_rows,
    make_env,
    metrics_table,
    write_answers,
    write_assignments,
    write_merge_cardset,
    write_pain,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def test_facet_audit_queue(env):
    run_id = "frun"
    high = [BASE + i for i in range(200)]
    low = [BASE + 200 + i for i in range(200)]
    write_answers(run_id, 0, high, [0.9] * 200)
    write_answers(run_id, 1, low, [0.1] * 200)
    # A second facet row: max over facets, and nulls are ignored.
    write_answers(run_id, 2, high, [0.4] * 200, question_id="paid")
    write_answers(run_id, 3, low, [None] * 200, question_id="paid")
    # Null-only comments are not candidates; other sets are ignored.
    write_answers(run_id, 4, [BASE + 500 + i for i in range(5)], [None] * 5)
    write_answers(run_id, 5, [BASE + 600], [0.9], question_set="screen@0")

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

    rows = gold_rows()
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


def test_assignment_audit_queue(env):
    run_id = "arun"
    junk_ids, pain = assignment_world(run_id)

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

    gold = [r for r in gold_rows() if r["label_set"] == "assignment_audit"]
    assert len(gold) == 200
    band_of = {
        c: b for b, info in q["bands"].items() for c in info["ids"]
    }
    for r in gold:
        assert r["purpose"] == "audit"
        assert r["selection_prob"] == pytest.approx(
            q["rates"][band_of[r["comment_id"]]]
        )


def test_merge_audit_queue(env):
    write_merge_cardset(env)
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

    gold = [r for r in gold_rows() if r["label_set"] == "merge_audit"]
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


def test_interview_queue(env):
    examples = {"c0001": [f"example sentence {i}" for i in range(7)]}
    q = audit_queues.interview_queue(
        metrics_table(), top_k=3, taxonomy_version="t9", cardset="synth",
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

    rows = gold_rows()
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
    write_assignments(run_id, "t9", [
        assignment_row(BASE, "g01", "c0001", 0.9),
        assignment_row(BASE + 1, "g01", "c0001", 0.9),
        assignment_row(BASE + 2, "g01", "c0006", 0.9),   # retired
        assignment_row(BASE + 3, "g01", "none", 0.9),
        assignment_row(BASE + 4, "g02", "c0005", 0.9),
        {**assignment_row(BASE + 5, "g01", "c0002", 0.9), "card_p": 0.2},
    ])
    write_pain(run_id, [
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
    rows = gold_rows()
    assert rows[0]["selection_prob"] is None
    # Only rows of this label set are replaced.
    audit_queues.write_gold(
        [dict(base, comment_id=BASE + 1)], "interview"
    )
    assert [r["comment_id"] for r in gold_rows()] == [BASE + 1]

"""L14 replies: pair builder, runner items, unsolved-per-problem table."""

import hashlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import contracts
from atlas.cards.replies import (
    FOLLOWUP_QUESTIONS,
    MAPPING,
    REPLY_QUESTIONS,
    followup_items,
    followup_question_set,
    mapping_table,
    reply_items,
    reply_pairs,
    reply_question_set,
    write_mapping,
)
from atlas.inference.questions import canonical_json

BASE = 9_300_000_000


def comment(**over):
    """A COMMENTS row; every field defaults to null, set what matters."""
    row = {f.name: None for f in contracts.COMMENTS}
    row.update(over)
    return row


def problem(pid, author="synthetic_author_a", **over):
    base = {
        "id": pid,
        "time": 1000,
        "text_norm": "synthetic problem text",
        "author": author,
        "state": "ok",
    }
    return comment(**{**base, **over})


def reply(
    rid,
    parent,
    time,
    text="synthetic reply text",
    author="synthetic_author_b",
    **over,
):
    base = {
        "id": rid,
        "parent_id": parent,
        "time": time,
        "text_norm": text,
        "author": author,
        "state": "ok",
    }
    return comment(**{**base, **over})


def write_comments(snapshot_dir, rows):
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=contracts.COMMENTS)
    pq.write_table(table, snapshot_dir / "comments.parquet")


def test_reply_pairs_orders_by_time_and_reply_id(tmp_path):
    p = BASE + 1
    write_comments(
        tmp_path,
        [
            problem(p),
            reply(BASE + 3, p, 300),
            reply(BASE + 2, p, 200),
            reply(BASE + 4, p, 200),  # same time as BASE+2, id breaks the tie
        ],
    )
    out = reply_pairs(tmp_path, [p])
    assert out.author_followups == []
    assert out.pairs == [
        {
            "problem_id": p,
            "reply_id": BASE + 2,
            "time": 200,
            "text": "synthetic reply text",
        },
        {
            "problem_id": p,
            "reply_id": BASE + 4,
            "time": 200,
            "text": "synthetic reply text",
        },
        {
            "problem_id": p,
            "reply_id": BASE + 3,
            "time": 300,
            "text": "synthetic reply text",
        },
    ]


def test_reply_pairs_ordered_by_problem_then_time(tmp_path):
    p1, p2 = BASE + 1, BASE + 2
    write_comments(
        tmp_path,
        [
            problem(p1),
            problem(p2),
            reply(BASE + 11, p2, 100),
            reply(BASE + 12, p1, 300),
            reply(BASE + 13, p2, 150),
            reply(BASE + 14, p1, 200),
        ],
    )
    out = reply_pairs(tmp_path, [p2, p1])  # request order does not matter
    assert [(r["problem_id"], r["reply_id"]) for r in out.pairs] == [
        (p1, BASE + 14),
        (p1, BASE + 12),
        (p2, BASE + 11),
        (p2, BASE + 13),
    ]


def test_reply_pairs_caps_at_max_replies(tmp_path):
    p = BASE + 1
    rows = [problem(p)] + [
        reply(BASE + 20 + i, p, 100 + i) for i in range(7)
    ]
    write_comments(tmp_path, rows)
    out = reply_pairs(tmp_path, [p])
    assert [r["reply_id"] for r in out.pairs] == [BASE + 20 + i for i in range(5)]
    out3 = reply_pairs(tmp_path, [p], max_replies=3)
    assert [r["reply_id"] for r in out3.pairs] == [BASE + 20 + i for i in range(3)]


def test_reply_pairs_excludes_dead_deleted_and_blank(tmp_path):
    p = BASE + 1
    write_comments(
        tmp_path,
        [
            problem(p),
            reply(BASE + 31, p, 100, state="dead"),
            reply(BASE + 32, p, 101, state="deleted"),
            reply(BASE + 33, p, 102, text=None),
            reply(BASE + 34, p, 103, text="   \n\t  "),
            reply(BASE + 35, p, 104),
        ],
    )
    out = reply_pairs(tmp_path, [p])
    assert [r["reply_id"] for r in out.pairs] == [BASE + 35]


def test_author_reply_goes_to_author_followups(tmp_path):
    p = BASE + 1
    write_comments(
        tmp_path,
        [
            problem(p, author="synthetic_author_a"),
            reply(
                BASE + 41,
                p,
                100,
                text="synthetic follow-up text",
                author="synthetic_author_a",
            ),
            reply(BASE + 42, p, 200),
        ],
    )
    out = reply_pairs(tmp_path, [p])
    assert [r["reply_id"] for r in out.pairs] == [BASE + 42]
    assert out.author_followups == [
        {
            "problem_id": p,
            "reply_id": BASE + 41,
            "time": 100,
            "text": "synthetic follow-up text",
        }
    ]


def test_followups_capped_separately_from_pairs(tmp_path):
    p = BASE + 1
    write_comments(
        tmp_path,
        [
            problem(p, author="synthetic_author_a"),
            *[
                reply(BASE + 50 + i, p, 100 + i, author="synthetic_author_a")
                for i in range(7)
            ],
            *[reply(BASE + 70 + i, p, 100 + i) for i in range(6)],
        ],
    )
    out = reply_pairs(tmp_path, [p])
    assert [r["reply_id"] for r in out.author_followups] == [
        BASE + 50 + i for i in range(5)
    ]
    assert [r["reply_id"] for r in out.pairs] == [BASE + 70 + i for i in range(5)]


def test_grandchild_and_non_requested_parent_excluded(tmp_path):
    p = BASE + 1
    write_comments(
        tmp_path,
        [
            problem(p),
            comment(
                id=BASE + 90,
                time=50,
                text_norm="synthetic unrelated comment",
                author="synthetic_author_c",
                state="ok",
            ),
            reply(BASE + 81, p, 100),
            reply(BASE + 82, BASE + 81, 110),  # reply to a reply
            reply(BASE + 83, BASE + 90, 120),  # parent not requested
        ],
    )
    out = reply_pairs(tmp_path, [p])
    assert [r["reply_id"] for r in out.pairs] == [BASE + 81]


def test_null_author_problem_keeps_null_author_replies_as_pairs(tmp_path):
    p = BASE + 1
    write_comments(
        tmp_path,
        [
            problem(p, author=None),
            reply(BASE + 91, p, 100, author=None),
            reply(BASE + 92, p, 101, author=None),
        ],
    )
    out = reply_pairs(tmp_path, [p])
    assert [r["reply_id"] for r in out.pairs] == [BASE + 91, BASE + 92]
    assert out.author_followups == []


def test_absent_problem_produces_nothing(tmp_path):
    write_comments(tmp_path, [problem(BASE + 1)])
    out = reply_pairs(tmp_path, [BASE + 1, BASE + 77])
    assert out.pairs == [] and out.author_followups == []


def test_empty_problem_ids_returns_empty_without_parquet(tmp_path):
    out = reply_pairs(tmp_path, [])
    assert out.pairs == [] and out.author_followups == []


def test_missing_comments_parquet_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        reply_pairs(tmp_path, [BASE + 1])


# ---- Task 14.2: items, questions, mapping ----


def pair_row(problem_id, reply_id, time, text="synthetic reply text"):
    return {
        "problem_id": problem_id,
        "reply_id": reply_id,
        "time": time,
        "text": text,
    }


def test_reply_items_build_runner_items_with_truncated_state():
    items = reply_items([pair_row(11, 21, 100, "x" * 1500)], {11: "synthetic pain"})
    assert items == [
        {
            "comment_id": 21,
            "problem_id": 11,
            "kind": "reply",
            "time": 100,
            "state": {"problem": "synthetic pain", "reply": "x" * 1200},
            "questions": REPLY_QUESTIONS,
        }
    ]
    assert items[0]["questions"] is not REPLY_QUESTIONS


def test_reply_items_missing_pain_sentence_raises_keyerror():
    with pytest.raises(KeyError):
        reply_items([pair_row(99, 21, 100)], {})


def test_item_questions_are_independent_deep_copies():
    items = reply_items(
        [pair_row(11, 21, 100), pair_row(11, 22, 101)], {11: "p"}
    )
    items[0]["questions"]["names_solution"]["criteria"]["true"] = "mutated"
    assert items[1]["questions"]["names_solution"]["criteria"]["true"] != "mutated"
    assert (
        REPLY_QUESTIONS["names_solution"]["criteria"]["true"]
        == "The reply names a specific existing tool, product, feature, "
        "or approach that addresses the problem."
    )


def test_followup_items_build_runner_items():
    items = followup_items(
        [pair_row(11, 22, 105, "synthetic follow-up")], {11: "synthetic pain"}
    )
    assert items == [
        {
            "comment_id": 22,
            "problem_id": 11,
            "kind": "followup",
            "time": 105,
            "state": {
                "problem": "synthetic pain",
                "followup": "synthetic follow-up",
            },
            "questions": FOLLOWUP_QUESTIONS,
        }
    ]
    assert items[0]["questions"] is not FOLLOWUP_QUESTIONS


def test_followup_items_missing_pain_sentence_raises_keyerror():
    with pytest.raises(KeyError):
        followup_items([pair_row(99, 21, 100)], {11: "p"})


def test_question_constants_shape():
    assert set(REPLY_QUESTIONS) == {"names_solution", "solution_kind"}
    assert REPLY_QUESTIONS["names_solution"]["type"] == "noul"
    assert set(REPLY_QUESTIONS["names_solution"]["criteria"]) == {
        "true",
        "false",
    }
    assert REPLY_QUESTIONS["solution_kind"]["type"] == "choice"
    assert set(REPLY_QUESTIONS["solution_kind"]["criteria"]) == {
        "commercial_product",
        "open_source_tool",
        "built_in_feature",
        "process_or_workaround",
        "none",
    }
    assert set(FOLLOWUP_QUESTIONS) == {"author_says_solved"}
    fq = FOLLOWUP_QUESTIONS["author_says_solved"]
    assert fq["type"] == "choice"
    assert set(fq["criteria"]) == {"solved", "still_unsolved", "unclear"}


def test_question_sets_labels_and_deterministic_sha():
    qs = reply_question_set()
    assert qs.name == "replies" and qs.version == 1 and qs.label == "replies@1"
    assert qs.state_fields == ["problem", "reply"]
    assert qs.questions == REPLY_QUESTIONS
    expected = hashlib.sha256(
        canonical_json(REPLY_QUESTIONS).encode("utf-8")
    ).hexdigest()
    assert qs.sha256 == expected == reply_question_set().sha256

    fqs = followup_question_set()
    assert (
        fqs.name == "reply-followups"
        and fqs.version == 1
        and fqs.label == "reply-followups@1"
    )
    assert fqs.state_fields == ["problem", "followup"]
    assert fqs.questions == FOLLOWUP_QUESTIONS
    expected_f = hashlib.sha256(
        canonical_json(FOLLOWUP_QUESTIONS).encode("utf-8")
    ).hexdigest()
    assert fqs.sha256 == expected_f == followup_question_set().sha256
    assert qs.sha256 != fqs.sha256


def test_mapping_table_schema_and_rows():
    items = reply_items([pair_row(11, 21, 100)], {11: "p"}) + followup_items(
        [pair_row(11, 22, 105)], {11: "p"}
    )
    table = mapping_table(items)
    assert table.schema == MAPPING
    assert table.to_pylist() == [
        {"reply_id": 21, "problem_id": 11, "kind": "reply", "time": 100},
        {"reply_id": 22, "problem_id": 11, "kind": "followup", "time": 105},
    ]


def test_mapping_table_empty_has_schema():
    table = mapping_table([])
    assert table.schema == MAPPING and table.num_rows == 0


def test_write_mapping_round_trip(tmp_path):
    items = reply_items([pair_row(11, 21, 100)], {11: "p"})
    path = write_mapping(items, tmp_path / "nested" / "mapping.parquet")
    assert path == tmp_path / "nested" / "mapping.parquet"
    back = pq.read_table(path)
    assert back.schema == MAPPING
    assert back.to_pylist() == [
        {"reply_id": 21, "problem_id": 11, "kind": "reply", "time": 100}
    ]

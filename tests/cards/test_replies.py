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
    unsolved_by_problem,
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


# ---- Task 14.3: unsolved share per problem ----


def answer_row(**over):
    """An ANSWERS row; every field defaults to null, set what matters."""
    base = {f.name: None for f in contracts.ANSWERS}
    base.update(run_id="r1", question_set="replies@1", cache_hit=False)
    base.update(over)
    return base


def answers_table(rows):
    return pa.Table.from_pylist(rows, schema=contracts.ANSWERS)


def mapping_of(*rows):
    """(reply_id, problem_id, kind, time) tuples -> MAPPING table."""
    return pa.Table.from_pylist(
        [
            {"reply_id": rid, "problem_id": pid, "kind": kind, "time": t}
            for rid, pid, kind, t in rows
        ],
        schema=MAPPING,
    )


def solution_answers(reply_id, noul, kind="open_source_tool"):
    return [
        answer_row(
            comment_id=reply_id,
            question_id="names_solution",
            qtype="noul",
            noul=noul,
        ),
        answer_row(
            comment_id=reply_id,
            question_id="solution_kind",
            qtype="choice",
            choice=kind,
        ),
    ]


def followup_answer(reply_id, choice):
    return answer_row(
        comment_id=reply_id,
        question_id="author_says_solved",
        qtype="choice",
        choice=choice,
    )


UNSOLVED_COLUMNS = [
    "comment_id",
    "n_replies",
    "any_solution_named",
    "solution_kinds",
    "author_says_solved",
    "unsolved",
    "solved_p",
]


def test_no_solution_named_is_unsolved():
    mapping = mapping_of((21, 11, "reply", 100))
    answers = answers_table(solution_answers(21, 0.1, kind="none"))
    out = unsolved_by_problem(answers, mapping)
    assert out.column_names == UNSOLVED_COLUMNS
    assert out.schema.field("comment_id").type == pa.int64()
    assert out.schema.field("solution_kinds").type == pa.list_(pa.string())
    assert out.schema.field("solved_p").type == pa.float64()
    assert out.to_pylist() == [
        {
            "comment_id": 11,
            "n_replies": 1,
            "any_solution_named": False,
            "solution_kinds": [],
            "author_says_solved": None,
            "unsolved": True,
            "solved_p": 0.0,
        }
    ]


def test_named_solution_is_solved_and_none_kind_excluded():
    mapping = mapping_of(
        (21, 11, "reply", 100),
        (22, 11, "reply", 200),
        (23, 11, "reply", 300),
    )
    answers = answers_table(
        solution_answers(21, 0.8, kind="open_source_tool")
        + solution_answers(22, 0.9, kind="none")
        + solution_answers(23, 0.6, kind="commercial_product")
    )
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["n_replies"] == 3
    assert row["any_solution_named"] is True
    assert row["solution_kinds"] == ["commercial_product", "open_source_tool"]
    assert row["unsolved"] is False and row["solved_p"] == 1.0


def test_below_threshold_ignored_and_threshold_parameter_respected():
    mapping = mapping_of((21, 11, "reply", 100))
    answers = answers_table(solution_answers(21, 0.8))
    (row,) = unsolved_by_problem(answers, mapping, threshold=0.9).to_pylist()
    assert row["any_solution_named"] is False and row["solution_kinds"] == []
    assert row["unsolved"] is True and row["solved_p"] == 0.0


def test_author_still_unsolved_overrides_named_solution():
    mapping = mapping_of((21, 11, "reply", 100), (31, 11, "followup", 200))
    answers = answers_table(
        solution_answers(21, 0.9) + [followup_answer(31, "still_unsolved")]
    )
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["any_solution_named"] is True and row["n_replies"] == 1
    assert row["author_says_solved"] == "still_unsolved"
    assert row["unsolved"] is True and row["solved_p"] == 0.0


def test_latest_non_unclear_followup_wins():
    mapping = mapping_of(
        (21, 11, "reply", 100),
        (31, 11, "followup", 200),
        (32, 11, "followup", 300),
        (33, 11, "followup", 400),
    )
    answers = answers_table(
        solution_answers(21, 0.9)
        + [
            followup_answer(31, "solved"),
            followup_answer(32, "still_unsolved"),
            followup_answer(33, "unclear"),
        ]
    )
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["author_says_solved"] == "still_unsolved"
    assert row["unsolved"] is True


def test_followup_tie_breaks_by_reply_id():
    mapping = mapping_of((31, 11, "followup", 200), (39, 11, "followup", 200))
    answers = answers_table(
        [followup_answer(31, "solved"), followup_answer(39, "still_unsolved")]
    )
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["author_says_solved"] == "still_unsolved"


def test_all_unclear_followups_report_unclear():
    mapping = mapping_of((31, 11, "followup", 200), (32, 11, "followup", 300))
    answers = answers_table(
        [followup_answer(31, "unclear"), followup_answer(32, "unclear")]
    )
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["author_says_solved"] == "unclear"


def test_author_saying_solved_wins_even_when_no_reply_names_a_tool():
    mapping = mapping_of((31, 11, "followup", 200))
    answers = answers_table([followup_answer(31, "solved")])
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["n_replies"] == 0 and row["any_solution_named"] is False
    assert row["author_says_solved"] == "solved"
    assert row["unsolved"] is False and row["solved_p"] == 1.0


def test_problem_with_only_unclear_followups_is_unsolved():
    mapping = mapping_of((31, 11, "followup", 200))
    answers = answers_table([followup_answer(31, "unclear")])
    (row,) = unsolved_by_problem(answers, mapping).to_pylist()
    assert row["unsolved"] is True and row["solved_p"] == 0.0


def test_problems_without_answers_are_omitted_and_sorted():
    mapping = mapping_of(
        (21, 12, "reply", 100),
        (22, 11, "reply", 100),
        (23, 13, "reply", 100),
    )
    answers = answers_table(
        solution_answers(21, 0.8) + solution_answers(22, 0.2)
    )
    out = unsolved_by_problem(answers, mapping)
    assert [r["comment_id"] for r in out.to_pylist()] == [11, 12]


def test_unrelated_question_ids_and_comment_ids_ignored():
    mapping = mapping_of((21, 11, "reply", 100))
    answers = answers_table(
        [
            answer_row(
                comment_id=21,
                question_id="domain",
                qtype="choice",
                choice="software_development",
            ),
            answer_row(
                comment_id=21,
                question_id="domain",
                qtype="choice",
                choice="other",
            ),
            answer_row(comment_id=999, question_id="names_solution", noul=0.9),
        ]
    )
    assert unsolved_by_problem(answers, mapping).num_rows == 0


def test_duplicate_answer_rows_raise():
    mapping = mapping_of((21, 11, "reply", 100))
    answers = answers_table(
        [
            answer_row(comment_id=21, question_id="names_solution", noul=0.1),
            answer_row(comment_id=21, question_id="names_solution", noul=0.9),
        ]
    )
    with pytest.raises(ValueError, match="duplicate"):
        unsolved_by_problem(answers, mapping)


def test_empty_answers_returns_empty_table():
    out = unsolved_by_problem(
        answers_table([]), mapping_of((21, 11, "reply", 100))
    )
    assert out.column_names == UNSOLVED_COLUMNS and out.num_rows == 0

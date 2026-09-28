import pyarrow as pa

from atlas.sampling.frame import build_frame, engagement_cutpoints


def comments_table():
    rows = [
        # id, story_id, period, thread_type, eligible
        (1, 100, "P01", "story", True),
        (2, 100, "P01", "story", True),
        (3, 200, "P02", "ask_hn", True),
        (4, 300, "P02", "show_hn", True),
        (5, 300, "P02", "show_hn", False),
    ]
    return pa.table(
        {
            "id": [r[0] for r in rows],
            "story_id": [r[1] for r in rows],
            "period": [r[2] for r in rows],
            "thread_type": [r[3] for r in rows],
            "eligible": [r[4] for r in rows],
        }
    )


def stories_table():
    return pa.table({"id": [100, 200, 300], "descendants": [5, 50, 500]})


def test_cutpoints_are_story_level_terciles():
    lo, hi = engagement_cutpoints(stories_table().column("descendants").to_pylist())
    assert (lo, hi) == (5, 50)


def test_frame_has_only_eligible_rows_and_stratum_labels():
    frame = build_frame(comments_table(), stories_table(), cutpoints=(5, 50))
    assert frame.column("comment_id").to_pylist() == [1, 2, 3, 4]
    assert frame.column("stratum").to_pylist() == [
        "P01|story|e1",
        "P01|story|e1",
        "P02|ask_hn|e2",
        "P02|show_hn|e3",
    ]


def test_missing_or_null_engagement_gets_e0():
    comments = pa.table(
        {
            "id": [1, 2, 3],
            "story_id": [100, None, 999],
            "period": ["P01", "P01", "P01"],
            "thread_type": ["story", "story", "story"],
            "eligible": [True, True, True],
        }
    )
    stories = pa.table({"id": [100], "descendants": pa.array([None], type=pa.int32())})
    frame = build_frame(comments, stories, cutpoints=(5, 50))
    assert frame.column("comment_id").to_pylist() == [1, 2, 3]
    assert frame.column("stratum").to_pylist() == [
        "P01|story|e0",
        "P01|story|e0",
        "P01|story|e0",
    ]

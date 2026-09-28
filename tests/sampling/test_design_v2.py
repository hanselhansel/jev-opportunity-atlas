import json

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from atlas import contracts
from atlas.sampling.design_v2 import (
    PAIN_PATTERNS_VERSION,
    design_stratum,
    length_bin,
    pain_flag,
    thread_group,
)


def test_pain_flag_first_person_pain():
    assert pain_flag("We spent two days fighting our CI cache last month.")
    assert pain_flag("I built a workaround script because the export keeps breaking.")
    assert pain_flag("Our team switched off Jira after the price hike.")
    assert not pain_flag("Rust 2.0 looks like a nice release.")
    assert PAIN_PATTERNS_VERSION == 1


def test_pain_flag_distance_and_edge_cases():
    # Pain term without a first-person marker nearby does not count.
    assert not pain_flag("The release notes say the exporter was completely broken.")
    # Marker alone is not enough.
    assert not pain_flag("I think the new API looks great.")
    # "i.e." never counts as a first-person marker.
    assert not pain_flag("The exporter is broken, i.e. it fails on every run.")
    # Distance is the gap between match spans; 80 chars is in range, 81 is not.
    assert pain_flag("I " + "x" * 78 + " broke")
    assert not pain_flag("I " + "x" * 79 + " broke")
    # Overlapping/adjacent matches count either order.
    assert pain_flag("My CI broke again.")
    # Non-stem terms need a word boundary: "hacker" is not "hack".
    assert not pain_flag("I read about a hacker who fixed my router remotely.")
    # Empty and None are False.
    assert not pain_flag("")
    assert not pain_flag(None)


def test_length_bins():
    assert [length_bin(n) for n in (3, 14, 15, 59, 60, 199, 200, 5000)] == [
        "L0",
        "L0",
        "L1",
        "L1",
        "L2",
        "L2",
        "L3",
        "L3",
    ]


def test_thread_groups():
    assert thread_group("ask_hn") == "ask" and thread_group("tell_hn") == "ask"
    assert thread_group("show_hn") == "show" and thread_group("launch_hn") == "show"
    assert thread_group("story") == "story"
    assert thread_group("poll") == "other" and thread_group("unknown") == "other"
    assert thread_group(None) == "other"


def test_design_stratum_label():
    assert design_stratum(pain=True, lbin="L2", period="P03", tgroup="ask") == (
        "pain|L2|H1|ask"
    )
    assert design_stratum(pain=False, lbin="L0", period="P11", tgroup="story") == (
        "nopain|L0|H2|story"
    )


def test_frame_v2_from_snapshot_tables():
    from atlas.sampling.design_v2 import build_frame_v2

    stories = pa.table(
        {
            "id": [9_000_000_100, 9_000_000_200],
            "thread_type": ["ask_hn", "show_hn"],
        }
    )
    # Unsorted on purpose: build_frame_v2 must sort by comment_id.
    comments = pa.table(
        {
            "id": [
                9_000_000_012,
                9_000_000_001,
                9_000_000_002,
                9_000_000_003,
                9_000_000_004,
            ],
            "story_id": [
                9_000_000_100,
                9_000_000_100,
                None,
                9_000_000_200,
                9_000_000_200,
            ],
            "period": ["P02", "P01", "P07", "P11", "P05"],
            "thread_type": ["story", None, "tell_hn", "poll", "story"],
            "text_norm": [
                "We spent two days fighting our CI cache.",
                "Nice release notes.",
                "I built a workaround for the export.",
                "Looks fine.",
                "Nice release notes.",
            ],
            "word_count": [30, 5, None, 4, 250],
            "eligible": [True, True, True, True, False],
        }
    )
    frame = build_frame_v2(comments, stories)
    assert frame.column_names == [
        "comment_id",
        "story_id",
        "stratum",
        "half",
        "period",
        "word_count",
    ]
    # Only eligible rows, sorted ascending.
    assert frame.column("comment_id").to_pylist() == [
        9_000_000_001,
        9_000_000_002,
        9_000_000_003,
        9_000_000_012,
    ]
    # Null thread_type falls back to the story's; the rest group on their own.
    expected_tt = ["ask", "ask", "other", "story"]
    rows = frame.to_pylist()
    for row, tgroup in zip(rows, expected_tt):
        sid = row["story_id"]
        assert row["half"] == (contracts.half_of(sid) if sid is not None else None)
        src = comments.filter(
            pc.equal(comments.column("id"), row["comment_id"])
        ).to_pylist()[0]
        assert row["stratum"] == design_stratum(
            pain_flag(src["text_norm"]),
            length_bin(src["word_count"] or 0),
            src["period"],
            tgroup,
        )
    assert frame.schema.field("comment_id").type == pa.int64()
    assert frame.schema.field("word_count").type == pa.int32()
    # Null word_count counts as 0 -> L0 for comment 9_000_000_002.
    assert rows[1]["word_count"] == 0
    assert rows[1]["stratum"].startswith("pain|L0|H2|ask")


def _v2_frame(n_a=300, n_b=700):
    ids = list(range(9_000_000_001, 9_000_000_001 + n_a + n_b))
    return pa.table(
        {
            "comment_id": ids,
            "story_id": [9_000_000_000 + i // 10 for i in range(n_a + n_b)],
            "stratum": ["pain|L1|H1|ask"] * n_a + ["nopain|L0|H2|story"] * n_b,
        }
    )


_ALLOC = {"pain|L1|H1|ask": 60, "nopain|L0|H2|story": 35}
_N = {"pain|L1|H1|ask": 300, "nopain|L0|H2|story": 700}


def test_draw_allocated_weights_and_manifest(tmp_path):
    from atlas.sampling.design_v2 import (
        design_block,
        draw_allocated,
        write_design_manifest,
    )

    frame = _v2_frame()
    table = draw_allocated(frame, _ALLOC, seed=7, sample_id="s2")
    assert table.schema == contracts.SAMPLE
    assert table.num_rows == 95
    rows = table.to_pylist()
    for r in rows:
        assert r["inclusion_prob"] == pytest.approx(
            _ALLOC[r["stratum"]] / _N[r["stratum"]]
        )
    assert sum(r["weight"] for r in rows) == pytest.approx(1000)
    assert all(r["batch"] == 1 for r in rows)
    assert [r["draw_order"] for r in rows] == list(range(95))

    same = draw_allocated(frame, _ALLOC, seed=7, sample_id="s2")
    assert same.column("comment_id").to_pylist() == (
        table.column("comment_id").to_pylist()
    )
    other = draw_allocated(frame, _ALLOC, seed=8, sample_id="s2")
    assert other.column("comment_id").to_pylist() != (
        table.column("comment_id").to_pylist()
    )

    design = design_block(
        floor_rate=0.02,
        min_n=30,
        budget_tokens=10_000,
        p={"pain|L1|H1|ask": 0.3, "nopain|L0|H2|story": 0.03},
        c={"pain|L1|H1|ask": 500.0, "nopain|L0|H2|story": 400.0},
        source="pilot:run-x",
        alloc=_ALLOC,
        N=_N,
    )
    write_design_manifest(table, {"seed": 7}, design, tmp_path)
    stored = json.loads((tmp_path / "s2.json").read_text())
    block = stored["design"]
    assert block["pain_patterns_version"] == 1
    assert block["floor_rate"] == 0.02
    assert block["budget_tokens"] == 10_000
    assert block["p_h"]["pain|L1|H1|ask"] == 0.3
    assert block["c_h"]["nopain|L0|H2|story"] == 400.0
    assert block["inputs_source"] == "pilot:run-x"
    assert block["allocation"] == _ALLOC
    assert block["expected_positives"] == pytest.approx(60 * 0.3 + 35 * 0.03)
    assert stored["seed"] == 7
    assert (tmp_path / "s2.parquet").exists()


def test_draw_allocated_rejects_bad_alloc():
    from atlas.sampling.design_v2 import draw_allocated

    frame = _v2_frame(5, 5)
    with pytest.raises(ValueError):
        # Missing a frame stratum entirely.
        draw_allocated(frame, {"pain|L1|H1|ask": 5}, 1, "x")
    with pytest.raises(ValueError):
        # A frame stratum with zero allocation.
        draw_allocated(
            frame,
            {"pain|L1|H1|ask": 0, "nopain|L0|H2|story": 3},
            1,
            "x",
        )
    with pytest.raises(ValueError):
        # Allocation larger than the stratum.
        draw_allocated(
            frame,
            {"pain|L1|H1|ask": 6, "nopain|L0|H2|story": 3},
            1,
            "x",
        )
    with pytest.raises(ValueError):
        # Positive allocation for a stratum that is not in the frame.
        draw_allocated(
            frame,
            {"pain|L1|H1|ask": 2, "nopain|L0|H2|story": 3, "ghost": 1},
            1,
            "x",
        )
    # Extra zero-valued keys are allowed.
    ok = draw_allocated(
        frame,
        {"pain|L1|H1|ask": 2, "nopain|L0|H2|story": 3, "ghost": 0},
        1,
        "x",
    )
    assert ok.num_rows == 5

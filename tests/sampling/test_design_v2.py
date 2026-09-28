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

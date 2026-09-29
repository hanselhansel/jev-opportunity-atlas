"""S5 task 2: tally() — per-tool and per-card named-fix counts.

fix_share = fix_threads / (fix_threads + complaint_threads) with a
stratified thread bootstrap (R = 1000, seed 0); tools under 10 threads stay
in the tallies marked sparse.
"""

from atlas.solutions import match, tally

TOOLS = [
    match.Tool(name="AWS", aliases=("aws",), category="cloud_infra"),
    match.Tool(name="Go", aliases=("golang",), category="dev_tool"),
    match.Tool(name="Deno", aliases=("deno",), category="dev_tool"),
]


def _m(comment_id, problem_id, card_id, story_id, kind, tool, stratum="s"):
    return {
        "hit_id": tally.hit_id(comment_id, tool),
        "comment_id": comment_id,
        "problem_id": problem_id,
        "card_id": card_id,
        "story_id": story_id,
        "stratum": stratum,
        "kind": kind,
        "tool": tool,
    }


def test_tally_counts_and_fix_share():
    mentions = [
        _m(1, 100, "c1", 10, "problem", "AWS"),       # complaint, S10
        _m(2, 100, "c1", 10, "reply", "AWS"),          # fix, S10
        _m(3, 200, "c2", 20, "reply", "AWS"),          # fix, S20
        _m(4, 200, "c2", 20, "reply", "Go"),           # fix, S20
        _m(5, 200, "c2", 20, "followup", "Go"),        # fix, S20
        _m(6, 300, "c2", 30, "reply", "Deno"),         # denied
    ]
    confirmed = {tally.hit_id(2, "AWS"), tally.hit_id(3, "AWS"),
                 tally.hit_id(4, "Go"), tally.hit_id(5, "Go")}
    tools_rows, card_tools = tally.tally(mentions, confirmed, TOOLS,
                                         n_boot=200)
    rows = {r["name"]: r for r in tools_rows}

    aws = rows["AWS"]
    assert aws["complaint_threads"] == 1
    assert aws["fix_threads"] == 2
    assert aws["threads"] == 2
    assert abs(aws["fix_share"]["est"] - 2 / 3) < 1e-9
    assert aws["fix_share"]["n"] == 2
    assert aws["sparse"] is True

    go = rows["Go"]
    # two confirmed mentions in one thread still count once
    assert go["fix_threads"] == 1 and go["fix_share"]["est"] == 1.0

    deno = rows["Deno"]
    assert deno["threads"] == 0 and deno["fix_share"] is None
    assert deno["sparse"] is True

    assert {f["name"]: f["threads"] for f in card_tools["c1"]["fixes"]} == {
        "AWS": 1
    }
    assert {b["name"] for b in card_tools["c1"]["blamed"]} == {"AWS"}
    assert {f["name"]: f["threads"] for f in card_tools["c2"]["fixes"]} == {
        "AWS": 1,
        "Go": 1,
    }
    assert card_tools["c2"]["blamed"] == []


def test_sparse_boundary_at_ten_threads():
    mentions = [
        _m(1000 + i, 100, "c1", 1000 + i, "problem", "AWS")
        for i in range(10)
    ]
    rows, _cards = tally.tally(mentions, set(), TOOLS, n_boot=50)
    aws = next(r for r in rows if r["name"] == "AWS")
    assert aws["threads"] == 10 and aws["sparse"] is False
    assert aws["fix_share"]["est"] == 0.0


def test_tally_deterministic_replicates():
    mentions = [
        _m(1, 100, "c1", 10, "problem", "AWS"),
        _m(2, 100, "c1", 10, "reply", "AWS"),
        _m(3, 200, "c2", 20, "reply", "AWS", stratum="t"),
        _m(4, 300, "c2", 30, "reply", "AWS", stratum="t"),
    ]
    confirmed = {tally.hit_id(2, "AWS"), tally.hit_id(3, "AWS")}
    a, _ = tally.tally(mentions, confirmed, TOOLS, n_boot=100)
    b, _ = tally.tally(mentions, confirmed, TOOLS, n_boot=100)
    assert a == b
    aws = next(r for r in a if r["name"] == "AWS")
    assert aws["fix_share"]["lo50"] <= aws["fix_share"]["est"]
    assert aws["fix_share"]["hi95"] >= aws["fix_share"]["lo95"]

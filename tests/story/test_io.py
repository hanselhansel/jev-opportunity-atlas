"""Task 1: story io helpers (atomic section merge, Est builder)."""

import json

from atlas.story import io


def test_merge_section_keeps_other_keys(tmp_path):
    path = tmp_path / "story.json"
    a = {"x": 1, "nested": {"y": [1, 2, 3]}}
    io.merge_section(path, "a", a)
    before = path.read_text()
    io.merge_section(path, "b", {"z": "w"})
    after = json.loads(path.read_text())
    assert json.dumps(after["a"], sort_keys=True) == json.dumps(
        json.loads(before)["a"], sort_keys=True
    )
    assert after["b"] == {"z": "w"}


def test_merge_section_creates_and_overwrites(tmp_path):
    path = tmp_path / "sub" / "story.json"
    io.merge_section(path, "a", 1)
    io.merge_section(path, "a", 2)
    assert json.loads(path.read_text())["a"] == 2


def test_est_builds_contract_object():
    e = io.est(0.5, 0.4, 0.6, 0.3, 0.7, 40)
    assert e == {
        "est": 0.5,
        "lo50": 0.4,
        "hi50": 0.6,
        "lo95": 0.3,
        "hi95": 0.7,
        "n": 40,
        "sparse": False,
    }
    assert io.est(0.5, n=10)["sparse"] is True
    assert io.est(None) is None

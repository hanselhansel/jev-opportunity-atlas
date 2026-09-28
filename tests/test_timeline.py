import json

from atlas import paths, timeline


def test_mark_appends_events(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "RUNS", tmp_path)
    timeline.mark("pilot_start")
    timeline.mark("first_validated_finding", note="stripe payouts")
    rows = [json.loads(line) for line in (tmp_path / "timeline.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows] == ["pilot_start", "first_validated_finding"]
    assert rows[1]["note"] == "stripe payouts" and rows[0]["at"].endswith("+00:00")

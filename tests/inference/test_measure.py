"""L22 22.3b: `jev measure` — real input-token counts per question set over
three synthetic comments (short/medium/long), through the project runner so
ledger entries are written under budget ``smoke``.
"""

import json
import re

import pytest

from atlas import paths
from atlas.inference import measure
from atlas.inference.ledger import read_rows
from tests.pilot.test_support import (  # noqa: F401
    make_transport,
    mock_env,
    pilot_repo,
)


def test_parse_sets():
    assert measure.parse_sets("screen@1,facets@1") == [
        ("screen", 1),
        ("facets", 1),
    ]
    assert measure.parse_sets("screen@1") == [("screen", 1)]
    with pytest.raises(ValueError, match="version"):
        measure.parse_sets("screen")
    with pytest.raises(ValueError, match="version"):
        measure.parse_sets("screen@x")


def test_measure_items_are_synthetic():
    assert len(measure.ITEMS) == 3
    ids = [it["comment_id"] for it in measure.ITEMS]
    assert all(i >= 9_900_000_000 for i in ids)
    # strictly increasing comment length: short < medium < long
    sizes = [len(it["comment"]) for it in measure.ITEMS]
    assert sizes[0] < sizes[1] < sizes[2]


def test_measure_dry_run(pilot_repo, monkeypatch, capsys):  # noqa: F811
    seen = []
    transport = make_transport(seen=seen)
    mock_env(monkeypatch, transport)
    monkeypatch.setattr(measure, "_transport", lambda: transport)
    out = measure.measure_tokens("screen@1,facets@1")
    assert out["dispatched"] is False
    assert seen == []
    printed = capsys.readouterr().out
    assert "screen@1" in printed
    assert "facets@1" in printed


def test_measure_runs_and_prints_table(pilot_repo, monkeypatch, capsys):  # noqa: F811
    seen = []
    transport = make_transport(seen=seen)
    mock_env(monkeypatch, transport)
    monkeypatch.setattr(measure, "_transport", lambda: transport)
    out = measure.measure_tokens("screen@1,facets@1", yes=True)
    assert out["dispatched"] is True
    assert len(seen) == 6  # 2 sets x 3 comments

    table = out["tokens"]
    assert set(table) == {"screen@1", "facets@1"}
    for toks in table.values():
        assert len(toks) == 3
        assert all(isinstance(t, int) and t > 0 for t in toks)
    # The mock counts request bytes, so the long comment costs more.
    assert table["screen@1"][2] > table["screen@1"][0]
    assert table["facets@1"][2] > table["facets@1"][0]

    printed = capsys.readouterr().out
    assert re.search(r"screen@1\s+\d+\s+\d+\s+\d+", printed)
    assert re.search(r"facets@1\s+\d+\s+\d+\s+\d+", printed)

    manifest = json.loads(
        (paths.run_dir(out["run_id"]) / "run_manifest.json").read_text()
    )
    assert manifest["budget"] == "smoke"
    assert out["run_id"].startswith("measure-")

    finals = [
        r
        for r in read_rows(paths.ledger_path(out["run_id"]))
        if r["cost_class"] in ("calculated", "unknown")
    ]
    assert len(finals) == 6
    assert {r["question_set"] for r in finals} == {"screen@1", "facets@1"}
    assert {r["comment_id"] for r in finals} == {
        it["comment_id"] for it in measure.ITEMS
    }

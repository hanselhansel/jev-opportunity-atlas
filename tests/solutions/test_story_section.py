"""`story data --with tools` finds the solutions section in the registry."""

import json
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq

import atlas.solutions.cli as solutions_cli
from atlas import paths
from atlas.solutions import tally
from atlas.story.cli import SECTIONS

CARDSET_YAML = """taxonomy_version: t0
groups:
  g01: {label: "Synthetic group"}
cards:
  - {card_id: n136, group_id: g01, statement: "Synthetic duplicate", status: merged_into:n014}
  - {card_id: n014, group_id: g01, statement: "Synthetic target", status: approved}
"""


def test_tools_section_registered():
    assert SECTIONS.get("tools") is solutions_cli.section


def test_section_resolves_merged_cards(tmp_path, monkeypatch):
    """A pre-merge tallies.json/mentions.parquet re-tallies under n014."""
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CONFIGS", tmp_path / "configs")
    cards_dir = paths.CONFIGS / "cards"
    cards_dir.mkdir(parents=True)
    (cards_dir / "syn.t0.yaml").write_text(CARDSET_YAML)
    out_dir = paths.run_dir("assign-r1") / "solutions"
    out_dir.mkdir(parents=True)
    (out_dir / "tallies.json").write_text(
        json.dumps(
            {
                "version": "t0",
                "tools": [{"name": "AWS", "threads": 3}],
                "cards_tools": {
                    "n136": {
                        "fixes": [],
                        "blamed": [{"name": "AWS", "threads": 3}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    mentions = [
        {
            "hit_id": 1,
            "comment_id": 9_000_000_001,
            "problem_id": 9_000_000_001,
            "card_id": "n136",
            "story_id": 9_500_000_010,
            "kind": "problem",
            "tool": "AWS",
            "time": 0,
        },
        {
            "hit_id": 2,
            "comment_id": 9_000_000_002,
            "problem_id": 9_000_000_002,
            "card_id": "n014",
            "story_id": 9_500_000_020,
            "kind": "problem",
            "tool": "AWS",
            "time": 0,
        },
    ]
    pq.write_table(
        pa.Table.from_pylist(mentions, schema=tally.MENTIONS),
        out_dir / "mentions.parquet",
    )
    story_path = tmp_path / "story.json"
    story_path.write_text(
        json.dumps({"cards": [{"id": "n014"}, {"id": "n136"}]}),
        encoding="utf-8",
    )
    args = SimpleNamespace(assign_run="assign-r1", cardset=None)
    solutions_cli.section(args, story_path)
    doc = json.loads(story_path.read_text(encoding="utf-8"))
    cards = {c["id"]: c for c in doc["cards"]}
    assert "tools" not in cards["n136"]
    blamed = {b["name"]: b["threads"] for b in cards["n014"]["tools"]["blamed"]}
    # the union of the two cards' mention threads, not the stored 3
    assert blamed == {"AWS": 2}


def test_section_merges_stored_keys_without_mentions(tmp_path, monkeypatch):
    """With no mentions.parquet the stored cards_tools keys still resolve."""
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CONFIGS", tmp_path / "configs")
    cards_dir = paths.CONFIGS / "cards"
    cards_dir.mkdir(parents=True)
    (cards_dir / "syn.t0.yaml").write_text(CARDSET_YAML)
    out_dir = paths.run_dir("assign-r1") / "solutions"
    out_dir.mkdir(parents=True)
    (out_dir / "tallies.json").write_text(
        json.dumps(
            {
                "version": "t0",
                "tools": [],
                "cards_tools": {
                    "n136": {
                        "fixes": [{"name": "Go", "threads": 2}],
                        "blamed": [{"name": "AWS", "threads": 3}],
                    },
                    "n014": {
                        "fixes": [],
                        "blamed": [{"name": "AWS", "threads": 1}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    story_path = tmp_path / "story.json"
    story_path.write_text(
        json.dumps({"cards": [{"id": "n014"}, {"id": "n136"}]}),
        encoding="utf-8",
    )
    args = SimpleNamespace(assign_run="assign-r1", cardset=None)
    solutions_cli.section(args, story_path)
    doc = json.loads(story_path.read_text(encoding="utf-8"))
    cards = {c["id"]: c for c in doc["cards"]}
    assert "tools" not in cards["n136"]
    blamed = {b["name"]: b["threads"] for b in cards["n014"]["tools"]["blamed"]}
    fixes = {f["name"]: f["threads"] for f in cards["n014"]["tools"]["fixes"]}
    assert blamed == {"AWS": 4}  # n136's 3 + n014's 1
    assert fixes == {"Go": 2}

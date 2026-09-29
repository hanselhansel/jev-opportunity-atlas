"""Task 4: story check, method section, and the story CLI."""

import json

import pytest

from tests.story import world

DATA_ARGS = [
    "--snapshot", world.SNAPSHOT,
    "--facet-sample", world.SAMPLE,
    "--facets-run", world.FACETS_RUN,
    "--assign-run", world.ASSIGN_RUN,
    "--cardset", "syn",
    "--version", world.TV,
    "--audit-run", world.AUDIT_RUN,
    "--benchmark-run", world.BENCH_RUN,
    "--robust-screen", "runs/robust-screen-compare.json",
    "--robust-assign", "runs/robust-assign-compare.json",
    "--run-phases", "configs/run_phases.toml",
    "--R", "200",
    "--seed", "0",
]


def _run_story(tmp_path, monkeypatch, argv):
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import cli

    return cli.main(argv)


def test_check_flags_unknown_string(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import check

    doc = {"meta": {"schema": "story.v1", "taxonomy": world.TV,
                    "title": "Startup opportunities identified via Hacker "
                             "News conversations between 2025-26",
                    "built_at": "2026-09-30T12:00:00Z"},
           "groups": [{"id": "g01", "label": "Synthetic group one",
                       "statement": "Synthetic need one"}]}
    path = tmp_path / "story.json"
    path.write_text(json.dumps(doc))
    assert check.check_story(path) == []

    doc["cards"] = [{"id": "c01",
                     "statement": "the exact wording of a leaked comment"}]
    doc["bad"] = {"author": "someuser"}
    path.write_text(json.dumps(doc))
    problems = check.check_story(path)
    assert any("author" in p for p in problems)
    assert any("leaked comment" in p for p in problems)


def test_check_flags_thin_term(tmp_path, monkeypatch):
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import check

    doc = {"terms": {"g01": [
        {"term": "kubernetes", "n_comments": 19, "n_authors": 30},
        {"term": "refunds", "n_comments": 40, "n_authors": 20},
    ]}}
    path = tmp_path / "story.json"
    path.write_text(json.dumps(doc))
    problems = check.check_story(path)
    assert len(problems) == 1 and "kubernetes" in problems[0]


def test_with_runs_registered_section(tmp_path, monkeypatch):
    calls = []
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import cli

    def _dummy(args, story_path):
        calls.append((args, story_path))

    monkeypatch.setitem(cli.SECTIONS, "dummy", _dummy)
    out = tmp_path / "story.json"
    cli.main(["story", "data", "--out", str(out), *DATA_ARGS,
              "--with", "dummy"])
    assert len(calls) == 1 and calls[0][1] == out


def test_only_with_skips_core(tmp_path, monkeypatch):
    calls = []
    world.build_world(tmp_path, monkeypatch)
    from atlas.story import cli

    monkeypatch.setitem(cli.SECTIONS, "dummy", lambda a, p: calls.append(p))
    out = tmp_path / "story.json"
    out.write_text(json.dumps({"meta": {"schema": "story.v1"}}))
    cli.main(["story", "data", "--out", str(out), *DATA_ARGS,
              "--with", "dummy", "--only-with"])
    assert len(calls) == 1
    assert json.loads(out.read_text())["meta"]["schema"] == "story.v1"
    assert "groups" not in json.loads(out.read_text())


def test_cli_writes_core_keys(tmp_path, monkeypatch, capsys):
    _run_story(tmp_path, monkeypatch,
               ["story", "data", "--out", str(tmp_path / "story.json"),
                *DATA_ARGS])
    doc = json.loads((tmp_path / "story.json").read_text())
    for key in ("meta", "funnel", "groups", "cards", "unplaced",
                "domains", "roles", "method"):
        assert key in doc, key
    runs = {r["run"]: r for r in doc["method"]["runs"]}
    assert runs[world.SCREEN_RUN]["phase"] == "screen"
    assert doc["method"]["quality"]["audit_jev"] == pytest.approx(0.81)
    assert doc["method"]["quality"]["audit_random"] == pytest.approx(0.12)
    assert doc["method"]["quality"]["benchmark_acc"] == pytest.approx(0.9)
    assert doc["method"]["quality"]["planted_recovery"] == pytest.approx(1.0)
    screen = doc["method"]["wording"]["screen"]
    assert any(r["run"] == world.SCREEN_RUN for r in screen)
    assert len(doc["method"]["wording"]["assign"]["card_agreement"]) == 2
    assert doc["meta"]["runs"]["replies"] == f"{world.ASSIGN_RUN}/replies"

    from atlas.story import cli

    capsys.readouterr()
    cli.main(["story", "check", str(tmp_path / "story.json")])
    assert "story: ok" in capsys.readouterr().out

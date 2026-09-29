"""L26 task 26.1: `cards induce` reassigns only the card-level residue when a
cardset grows from t2 to a superset t3 (same groups and labels, every t2 card
unchanged, new cards added). The group answer is already known, so no
group-level call may fire.

L30 task 30.1: `--scope all` re-asks the card level for every base row with a
real group, so rows already on a base card can move to a card added in the new
version. `--scope residue` (the default) is unchanged. Equal base and new
versions are allowed only with `--scope all`."""

import json
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, paths
from atlas.cards.engine import cli as cards_cli
from atlas.cards.engine import induce as induce_mod
from atlas.cards.engine.assign import AssignResult, write_assignments
from atlas.cards.engine.cardset import Card, CardSet, CardSetError
from atlas.inference import keys
from tests.cards.test_engine_support import CANARY, make_transport

ROOT = Path(__file__).resolve().parents[3]

GROUPS = {"g1": "Alpha needs", "g2": "Beta needs"}
T2_CARDS = [
    Card("a1", "g1", "alpha one need", "approved"),
    Card("a2", "g1", "alpha two need", "approved"),
    Card("b1", "g2", "beta one need", "approved"),
]
T3_CARDS = T2_CARDS + [
    Card("a3", "g1", "alpha three need", "approved"),
    Card("b2", "g2", "beta two need", "approved"),
]

BASE_YAML = """\
taxonomy_version: t2
groups:
  g1: {label: "Alpha needs"}
  g2: {label: "Beta needs"}
cards:
  - {card_id: a1, group_id: g1, statement: "alpha one need", status: approved}
  - {card_id: a2, group_id: g1, statement: "alpha two need", status: approved}
  - {card_id: b1, group_id: g2, statement: "beta one need", status: approved}
"""

NEW_YAML = """\
taxonomy_version: t3
groups:
  g1: {label: "Alpha needs"}
  g2: {label: "Beta needs"}
cards:
  - {card_id: a1, group_id: g1, statement: "alpha one need", status: approved}
  - {card_id: a2, group_id: g1, statement: "alpha two need", status: approved}
  - {card_id: b1, group_id: g2, statement: "beta one need", status: approved}
  - {card_id: a3, group_id: g1, statement: "alpha three need", status: approved}
  - {card_id: b2, group_id: g2, statement: "beta two need", status: approved}
"""


def _cardset(version, cards, groups=None):
    d = {c.card_id: c for c in cards}
    return CardSet("mini", version, dict(groups or GROUPS), dict(d), dict(d), "x" * 64)


def _row(cid, group, card, card_p=0.9):
    return {
        "run_id": "rb",
        "comment_id": cid,
        "taxonomy_version": "t2",
        "group_id": group,
        "group_p": 0.9,
        "group_confidence": 0.9,
        "card_id": card,
        "card_p": card_p,
        "card_confidence": 0.9,
        "verified_p": None,
    }


def test_check_superset_accepts_added_cards():
    induce_mod.check_superset(_cardset("t2", T2_CARDS), _cardset("t3", T3_CARDS))


def test_check_superset_rejects_group_label_change():
    bad = _cardset("t3", T3_CARDS, groups={"g1": "Renamed needs", "g2": "Beta needs"})
    with pytest.raises(CardSetError):
        induce_mod.check_superset(_cardset("t2", T2_CARDS), bad)


def test_check_superset_rejects_group_added_or_dropped():
    with pytest.raises(CardSetError):
        induce_mod.check_superset(
            _cardset("t2", T2_CARDS),
            _cardset("t3", T3_CARDS, groups={**GROUPS, "g3": "Extra"}),
        )
    with pytest.raises(CardSetError):
        induce_mod.check_superset(
            _cardset("t2", T2_CARDS), _cardset("t3", T3_CARDS, groups={"g1": "Alpha needs"})
        )


def test_check_superset_rejects_card_statement_change():
    cards = [Card("a1", "g1", "rewritten need", "approved"), *T2_CARDS[1:]]
    with pytest.raises(CardSetError):
        induce_mod.check_superset(_cardset("t2", T2_CARDS), _cardset("t3", cards))


def test_check_superset_rejects_card_group_change():
    cards = [Card("a1", "g2", "alpha one need", "approved"), *T2_CARDS[1:]]
    with pytest.raises(CardSetError):
        induce_mod.check_superset(_cardset("t2", T2_CARDS), _cardset("t3", cards))


def test_check_superset_rejects_removed_or_status_changed_card():
    with pytest.raises(CardSetError):
        induce_mod.check_superset(_cardset("t2", T2_CARDS), _cardset("t3", T2_CARDS[:2]))
    cards = [Card("a1", "g1", "alpha one need", "retired"), *T2_CARDS[1:]]
    with pytest.raises(CardSetError):
        induce_mod.check_superset(_cardset("t2", T2_CARDS), _cardset("t3", cards))


def test_residue_selects_only_ingroup_unassigned():
    rows = [
        _row(9_000_000_601, "g1", "a1", 0.9),      # carried: assigned
        _row(9_000_000_602, "g1", "none", 1.0),    # residue: card none
        _row(9_000_000_603, "g2", "b1", 0.3),      # residue: low card_p
        _row(9_000_000_604, "none", None, None),   # carried: group none
        _row(9_000_000_605, "g2", None, None),     # residue: card null
        _row(9_000_000_606, "g1", "a2", 0.5),      # carried: boundary p
    ]
    ids = [r["comment_id"] for r in induce_mod.residue(rows)]
    assert ids == [9_000_000_602, 9_000_000_603, 9_000_000_605]


def _configs(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    (configs / "cards").mkdir(parents=True)
    for name in ("budgets.toml", "prices.toml"):
        (configs / name).write_bytes((ROOT / "configs" / name).read_bytes())
    (configs / "cards" / "mini.t2.yaml").write_text(BASE_YAML, encoding="utf-8")
    (configs / "cards" / "mini.t3.yaml").write_text(NEW_YAML, encoding="utf-8")
    monkeypatch.setattr(paths, "CONFIGS", configs)


def _yes_env(tmp_path, monkeypatch, transport):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("TYPESAFE_API_KEY", CANARY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://mock")
    monkeypatch.setattr(keys, "_keychain", lambda: pytest.fail("keychain read"))
    monkeypatch.setattr(cards_cli, "_transport", lambda: transport)


def _base_rows():
    return [
        _row(9_000_000_601, "g1", "a1", 0.9),
        _row(9_000_000_602, "g1", "none", 1.0),
        _row(9_000_000_603, "g2", "b1", 0.3),
        _row(9_000_000_604, "none", None, None),
        _row(9_000_000_605, "g1", None, None),
    ]


def _write_base_run(tmp_path):
    run_dir = paths.run_dir("rb")
    run_dir.mkdir(parents=True)
    meta = {
        9_000_000_601: {
            "low_confidence": False,
            "card_top2": ["a1", "a2"],
            "group_probs": {"g1": 0.9, "g2": 0.1, "none": 0.0},
            "card_probs": {"a1": 0.9, "a2": 0.1, "none": 0.0},
        },
        9_000_000_602: {
            "low_confidence": False,
            "card_top2": [],
            "group_probs": {"g1": 0.9, "g2": 0.1, "none": 0.0},
            "card_probs": {"a1": 0.0, "a2": 0.0, "none": 1.0},
        },
    }
    write_assignments(run_dir, AssignResult(rows=_base_rows(), meta=meta), "t2")
    pain = [
        {"comment_id": r["comment_id"], "pain_sentence": "x"}
        for r in _base_rows()
    ]
    pq.write_table(
        pa.Table.from_pylist(pain, schema=cards_cli.PAIN_SCHEMA),
        str(run_dir / "pain.parquet"),
    )


def _items_file(tmp_path):
    rows = [
        {"comment_id": 9_000_000_601, "pain_sentence": "alpha keep pain",
         "sentences": ["alpha keep pain"]},
        {"comment_id": 9_000_000_602, "pain_sentence": "alpha three pain",
         "sentences": ["alpha three pain", "more context"]},
        {"comment_id": 9_000_000_603, "pain_sentence": "beta two pain",
         "sentences": ["beta two pain"]},
        {"comment_id": 9_000_000_605, "pain_sentence": "stray pain",
         "sentences": ["stray pain"]},
    ]
    path = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    return str(path)


def _chooser(state, qid, options):
    assert qid == "card"  # no group-level call may fire
    return {"alpha three pain": "a3", "beta two pain": "b2"}.get(
        state["problem"], "none"
    )


def _chooser_all(state, qid, options):
    assert qid == "card"  # no group-level call may fire
    return {
        "alpha keep pain": "a2",    # 601: a1 -> a2
        "alpha three pain": "a3",   # 602: none -> a3
        "beta two pain": "b1",      # 603: b1 -> b1 (unchanged)
        "stray pain": "a3",         # 605: null -> a3
    }[state["problem"]]


def _induce_args(items, *extra):
    return [
        "cards", "induce", "--base-run", "rb", "--base-version", "t2",
        "--cardset", "mini", "--version", "t3", "--run", "r3",
        "--items", items, *extra,
    ]


def test_induce_parse_defaults():
    args = cli.build_parser().parse_args(_induce_args("x.parquet"))
    assert args.cards_command == "induce"
    assert args.budget == "assign" and args.rpm == 1000 and args.concurrency == 8
    assert args.base_run == "rb" and args.base_version == "t2"
    assert args.scope == "residue"
    args = cli.build_parser().parse_args(_induce_args("x.parquet", "--scope", "all"))
    assert args.scope == "all"


def test_induce_dry_run_prints_estimate_only(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(keys, "get_api_key", lambda: pytest.fail("key read"))
    monkeypatch.setattr(cards_cli, "_transport", lambda: pytest.fail("client"))
    _write_base_run(tmp_path)
    args = cli.build_parser().parse_args(_induce_args(_items_file(tmp_path)))
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "induce"
    assert out["estimated_calls"] == 3  # residue rows only
    assert out["estimated_input_tokens"] > 0 and out["estimated_usd"] > 0
    budgets = tomllib.loads((paths.CONFIGS / "budgets.toml").read_text())
    assert out["budget"] == "assign" and out["cap_usd"] == budgets["assign"]
    assert not (tmp_path / "runs" / "r3").exists()


def test_induce_rejects_non_superset_before_estimate(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    bad = NEW_YAML.replace("alpha one need", "rewritten need")
    (tmp_path / "configs" / "cards" / "mini.t3.yaml").write_text(
        bad, encoding="utf-8"
    )
    _write_base_run(tmp_path)
    args = cli.build_parser().parse_args(_induce_args(_items_file(tmp_path)))
    with pytest.raises(CardSetError):
        args.func(args)
    assert capsys.readouterr().out == ""


def test_induce_missing_items_fails(tmp_path, monkeypatch):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    _write_base_run(tmp_path)
    rows = [
        {"comment_id": 9_000_000_602, "pain_sentence": "alpha three pain",
         "sentences": ["alpha three pain"]},
    ]
    path = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    args = cli.build_parser().parse_args(_induce_args(str(path)))
    with pytest.raises(ValueError, match="residue"):
        args.func(args)


def test_induce_end_to_end(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(tmp_path, monkeypatch, make_transport(chooser=_chooser, seen=seen))
    _write_base_run(tmp_path)
    args = cli.build_parser().parse_args(
        _induce_args(_items_file(tmp_path), "--yes")
    )
    args.func(args)
    first = json.JSONDecoder().raw_decode(capsys.readouterr().out)[0]
    assert first["command"] == "induce" and first["estimated_calls"] == 3

    bodies = [json.loads(r.content) for r in seen]
    assert len(bodies) == 3
    assert all(list(b["questions"]) == ["card"] for b in bodies)
    by_problem = {
        b["state"]["problem"]: list(b["questions"]["card"]["criteria"])
        for b in bodies
    }
    assert by_problem["alpha three pain"] == ["a1", "a2", "a3", "none"]
    assert by_problem["beta two pain"] == ["b1", "b2", "none"]

    run_dir = paths.run_dir("r3")
    table = pq.read_table(run_dir / "assignments-t3.parquet")
    rows = {r["comment_id"]: r for r in table.to_pylist()}
    assert set(rows) == {
        9_000_000_601, 9_000_000_602, 9_000_000_603, 9_000_000_604, 9_000_000_605
    }
    assert all(
        r["run_id"] == "r3" and r["taxonomy_version"] == "t3"
        for r in rows.values()
    )
    carried = {
        k: v
        for k, v in rows[9_000_000_601].items()
        if k not in ("run_id", "taxonomy_version")
    }
    base = {
        k: v for k, v in _base_rows()[0].items()
        if k not in ("run_id", "taxonomy_version")
    }
    assert carried == base
    assert rows[9_000_000_602]["card_id"] == "a3"
    assert rows[9_000_000_602]["card_p"] == 1.0
    assert rows[9_000_000_602]["group_id"] == "g1"
    assert rows[9_000_000_603]["card_id"] == "b2"
    assert rows[9_000_000_603]["group_p"] == 0.9
    assert rows[9_000_000_605]["card_id"] == "none"  # still residue
    assert rows[9_000_000_605]["group_id"] == "g1"
    assert rows[9_000_000_604]["group_id"] == "none"
    assert rows[9_000_000_604]["card_id"] is None

    meta = json.loads((run_dir / "assignments-t3.meta.json").read_text())
    assert meta[str(9_000_000_602)]["card_top2"] == ["a3", "a1"]
    assert meta[str(9_000_000_602)]["card_probs"] == {
        "a1": 0.0, "a2": 0.0, "a3": 1.0, "none": 0.0
    }
    assert meta[str(9_000_000_602)]["group_probs"] == {
        "g1": 0.9, "g2": 0.1, "none": 0.0
    }
    assert meta[str(9_000_000_601)]["card_top2"] == ["a1", "a2"]  # carried meta

    side = json.loads((run_dir / "induce-t3.json").read_text())
    assert side["base_run"] == "rb" and side["base_version"] == "t2"
    assert side["taxonomy_version"] == "t3"
    assert side["scope"] == "residue"
    assert side["carried"] == 2 and side["reassigned"] == 3
    assert side["moved_to_card"] == 2
    assert side["changed_card"] == 2  # 602 none->a3, 603 b1->b2; 605 stayed none
    assert side["new_card_assignments"] == {"a3": 1, "b2": 1}
    assert pq.read_table(run_dir / "pain.parquet").num_rows == 5


def test_induce_rerun_resumes_without_paid_calls(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(tmp_path, monkeypatch, make_transport(chooser=_chooser, seen=seen))
    _write_base_run(tmp_path)
    items = _items_file(tmp_path)
    argv = _induce_args(items, "--yes")
    args = cli.build_parser().parse_args(argv)
    args.func(args)
    assert len(seen) == 3
    capsys.readouterr()
    args = cli.build_parser().parse_args(argv)
    args.func(args)
    assert len(seen) == 3  # every residue item was already done
    rows = pq.read_table(paths.run_dir("r3") / "assignments-t3.parquet").to_pylist()
    assert len(rows) == 5


def test_induce_scope_all_end_to_end(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(
        tmp_path, monkeypatch, make_transport(chooser=_chooser_all, seen=seen)
    )
    _write_base_run(tmp_path)
    args = cli.build_parser().parse_args(
        _induce_args(_items_file(tmp_path), "--scope", "all", "--yes")
    )
    args.func(args)
    first = json.JSONDecoder().raw_decode(capsys.readouterr().out)[0]
    assert first["command"] == "induce" and first["estimated_calls"] == 4

    bodies = [json.loads(r.content) for r in seen]
    assert len(bodies) == 4  # every base row with a real group
    assert all(list(b["questions"]) == ["card"] for b in bodies)
    by_problem = {
        b["state"]["problem"]: list(b["questions"]["card"]["criteria"])
        for b in bodies
    }
    assert by_problem["alpha keep pain"] == ["a1", "a2", "a3", "none"]
    assert by_problem["alpha three pain"] == ["a1", "a2", "a3", "none"]
    assert by_problem["beta two pain"] == ["b1", "b2", "none"]
    assert by_problem["stray pain"] == ["a1", "a2", "a3", "none"]
    answers = pq.read_table(paths.run_dir("r3") / "answers").to_pylist()
    assert {r["question_set"] for r in answers} == {"assign-c@t3"}

    run_dir = paths.run_dir("r3")
    rows = {
        r["comment_id"]: r
        for r in pq.read_table(run_dir / "assignments-t3.parquet").to_pylist()
    }
    assert set(rows) == {
        9_000_000_601, 9_000_000_602, 9_000_000_603, 9_000_000_604,
        9_000_000_605,
    }
    assert all(
        r["run_id"] == "r3" and r["taxonomy_version"] == "t3"
        for r in rows.values()
    )
    assert rows[9_000_000_601]["card_id"] == "a2"  # moved within its base group
    assert rows[9_000_000_601]["group_id"] == "g1"
    assert rows[9_000_000_602]["card_id"] == "a3"
    assert rows[9_000_000_603]["card_id"] == "b1"  # re-asked, same card
    assert rows[9_000_000_605]["card_id"] == "a3"
    carried = {
        k: v
        for k, v in rows[9_000_000_604].items()
        if k not in ("run_id", "taxonomy_version")
    }
    base = {
        k: v for k, v in _base_rows()[3].items()
        if k not in ("run_id", "taxonomy_version")
    }
    assert carried == base  # group-none row carried unchanged

    meta = json.loads((run_dir / "assignments-t3.meta.json").read_text())
    assert meta[str(9_000_000_601)]["card_top2"][0] == "a2"  # fresh card meta
    assert meta[str(9_000_000_601)]["group_probs"] == {
        "g1": 0.9, "g2": 0.1, "none": 0.0
    }

    side = json.loads((run_dir / "induce-t3.json").read_text())
    assert side["scope"] == "all"
    assert side["base_run"] == "rb" and side["base_version"] == "t2"
    assert side["carried"] == 1 and side["reassigned"] == 4
    assert side["moved_to_card"] == 4
    assert side["changed_card"] == 3  # 601 a1->a2, 602 none->a3, 605 null->a3
    assert side["new_card_assignments"] == {"a3": 2, "b2": 0}


def test_induce_scope_change_resumes(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(
        tmp_path, monkeypatch, make_transport(chooser=_chooser_all, seen=seen)
    )
    _write_base_run(tmp_path)
    items = _items_file(tmp_path)
    args = cli.build_parser().parse_args(_induce_args(items, "--yes"))
    args.func(args)
    assert len(seen) == 3
    capsys.readouterr()

    args = cli.build_parser().parse_args(
        _induce_args(items, "--scope", "all", "--yes")
    )
    args.func(args)
    capsys.readouterr()
    assert len(seen) == 4  # only 601 was owed; residue rows were already done
    assert json.loads(seen[-1].content)["state"]["problem"] == "alpha keep pain"

    rows = {
        r["comment_id"]: r
        for r in pq.read_table(
            paths.run_dir("r3") / "assignments-t3.parquet"
        ).to_pylist()
    }
    assert rows[9_000_000_601]["card_id"] == "a2"
    assert rows[9_000_000_602]["card_id"] == "a3"  # residue answer reused
    assert rows[9_000_000_603]["card_id"] == "b1"
    assert rows[9_000_000_605]["card_id"] == "a3"
    side = json.loads((paths.run_dir("r3") / "induce-t3.json").read_text())
    assert side["scope"] == "all" and side["changed_card"] == 3


def _t3_row(cid, group, card, card_p=0.9):
    return {**_row(cid, group, card, card_p), "taxonomy_version": "t3"}


def _write_t3_base_run(tmp_path, run_id="rc"):
    """A base run already stamped t3, as `cards induce` or `cards combine`
    produces for the mixed-path main run."""
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True)
    rows = [
        _t3_row(9_000_000_601, "g1", "a1", 0.9),
        _t3_row(9_000_000_602, "g1", "a3", 0.9),
        _t3_row(9_000_000_603, "g2", "none", 1.0),
        _t3_row(9_000_000_604, "none", None, None),
    ]
    write_assignments(run_dir, AssignResult(rows=rows), "t3")
    pain = [
        {"comment_id": r["comment_id"], "pain_sentence": "x"} for r in rows
    ]
    pq.write_table(
        pa.Table.from_pylist(pain, schema=cards_cli.PAIN_SCHEMA),
        str(run_dir / "pain.parquet"),
    )


def _induce_t3_args(items, *extra):
    return [
        "cards", "induce", "--base-run", "rc", "--base-version", "t3",
        "--cardset", "mini", "--version", "t3", "--run", "r4",
        "--items", items, *extra,
    ]


def test_induce_same_version_scope_all(tmp_path, monkeypatch, capsys):
    seen = []
    _yes_env(
        tmp_path, monkeypatch, make_transport(chooser=_chooser_all, seen=seen)
    )
    _write_t3_base_run(tmp_path)
    args = cli.build_parser().parse_args(
        _induce_t3_args(_items_file(tmp_path), "--scope", "all", "--yes")
    )
    args.func(args)
    capsys.readouterr()
    assert len(seen) == 3  # every real-group row re-asked under assign-c@t3
    answers = pq.read_table(paths.run_dir("r4") / "answers").to_pylist()
    assert {r["question_set"] for r in answers} == {"assign-c@t3"}
    rows = {
        r["comment_id"]: r
        for r in pq.read_table(
            paths.run_dir("r4") / "assignments-t3.parquet"
        ).to_pylist()
    }
    assert rows[9_000_000_601]["card_id"] == "a2"
    assert rows[9_000_000_602]["card_id"] == "a3"  # re-asked, same card
    assert rows[9_000_000_603]["card_id"] == "b1"  # was residue
    assert rows[9_000_000_604]["card_id"] is None
    side = json.loads((paths.run_dir("r4") / "induce-t3.json").read_text())
    assert side["scope"] == "all" and side["base_version"] == "t3"
    assert side["changed_card"] == 2  # 601 a1->a2, 603 none->b1
    assert side["new_card_assignments"] == {}


def test_induce_same_version_residue_rejected(tmp_path, monkeypatch, capsys):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    args = cli.build_parser().parse_args(_induce_t3_args("x.parquet"))
    with pytest.raises(SystemExit):
        args.func(args)
    assert capsys.readouterr().out == ""


def test_induce_scope_all_missing_items_fails(tmp_path, monkeypatch):
    _configs(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    _write_base_run(tmp_path)
    rows = [  # only the residue rows; 601 is owed under --scope all
        {"comment_id": 9_000_000_602, "pain_sentence": "alpha three pain",
         "sentences": ["alpha three pain"]},
        {"comment_id": 9_000_000_603, "pain_sentence": "beta two pain",
         "sentences": ["beta two pain"]},
        {"comment_id": 9_000_000_605, "pain_sentence": "stray pain",
         "sentences": ["stray pain"]},
    ]
    path = tmp_path / "items.parquet"
    pq.write_table(pa.Table.from_pylist(rows), str(path))
    args = cli.build_parser().parse_args(
        _induce_args(str(path), "--scope", "all")
    )
    with pytest.raises(ValueError, match="scope all"):
        args.func(args)

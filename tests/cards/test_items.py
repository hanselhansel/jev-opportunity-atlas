"""L23 task 23.1: build_items / draft_sample and the `cards items` /
`cards draft-sample` commands, ported from the main run's scratch script.

Synthetic fixtures only: comment ids are >= 9,000,000,000 and every string is
invented. Answers use the facets@2 question ids (account_type, pain_sentence,
domain, severity).
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import cli, contracts, paths
from atlas.cards import items as items_mod

ROOT = Path(__file__).resolve().parents[2]
BASE = 9_400_000_000
SNAP = "snap-l23"
SAMPLE = "facets-l23"
FACETS_RUN = "facets-run-l23"


def _comment(cid, sentences, **over):
    row = {f.name: None for f in contracts.COMMENTS}
    row.update(
        id=cid,
        time=1000,
        text_norm=". ".join(sentences),
        sentences=sentences,
        state="ok",
        **over,
    )
    return row


def _story(sid):
    row = {f.name: None for f in contracts.STORIES}
    row.update(id=sid, time=999, title="synthetic story", state="ok")
    return row


def _write_snapshot(snap_dir, comments):
    snap_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(comments, schema=contracts.COMMENTS),
        snap_dir / "comments.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([_story(BASE)], schema=contracts.STORIES),
        snap_dir / "stories.parquet",
    )


def _sample_row(cid, phase, half, weight):
    return {
        "comment_id": cid,
        "story_id": BASE,
        "stratum": "pain|L1|H1|ask",
        "half": half,
        "phase": phase,
        "w1": weight,
        "p2": 0.5,
        "weight": weight,
        "firsthand_p": 0.9 if phase == "pos" else 0.1,
    }


def _answer(cid, qid, qtype, **fields):
    row = {f.name: None for f in contracts.ANSWERS}
    row.update(
        run_id=FACETS_RUN,
        comment_id=cid,
        question_set="facets@2",
        question_id=qid,
        qtype=qtype,
        cache_hit=False,
        **fields,
    )
    return row


def _write_facets_run(run_dir, rows):
    answers = run_dir / "answers"
    answers.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=contracts.ANSWERS),
        answers / "part-0.parquet",
    )


def _facet_answers(cid, account_type, pain_choice, domain="work_careers", sev=2.0):
    return [
        _answer(cid, "account_type", "choice", choice=account_type),
        _answer(cid, "pain_sentence", "choice", choice=pain_choice),
        _answer(cid, "domain", "choice", choice=domain),
        _answer(cid, "severity", "score", score=sev),
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A facets run + sample + snapshot, all under tmp_path via paths."""
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "SAMPLES", tmp_path / "samples")
    monkeypatch.setattr(paths, "SNAPSHOTS", tmp_path / "snapshots")
    comments = [
        _comment(BASE + 1, ["first s0", "first s1"]),   # pos, explore
        _comment(BASE + 2, ["second s0", "second s1"]),  # pos, confirm
        _comment(BASE + 3, ["third s0"]),                # neg, explore
        _comment(BASE + 4, ["fourth s0"]),               # pos, explore, bad choice
        _comment(BASE + 5, ["fifth s0"]),                # pos, explore, not firsthand
        _comment(BASE + 6, ["sixth s0", "sixth s1", "sixth s2"]),
    ]
    _write_snapshot(paths.snapshot_dir(SNAP), comments)
    sample_rows = [
        _sample_row(BASE + 1, "pos", "explore", 10.0),
        _sample_row(BASE + 2, "pos", "confirm", 20.0),
        _sample_row(BASE + 3, "neg", "explore", 30.0),
        _sample_row(BASE + 4, "pos", "explore", 40.0),
        _sample_row(BASE + 5, "pos", "explore", 50.0),
        _sample_row(BASE + 6, "pos", "explore", 60.0),
    ]
    paths.SAMPLES.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(sample_rows), paths.sample_path(SAMPLE)
    )
    answers = (
        _facet_answers(BASE + 1, "firsthand_account", "s1")
        + _facet_answers(BASE + 2, "firsthand_account", "s0")
        + _facet_answers(BASE + 3, "firsthand_account", "s0")
        + _facet_answers(BASE + 4, "firsthand_account", "s9")
        + _facet_answers(BASE + 5, "general_opinion", "s0")
        + _facet_answers(BASE + 6, "firsthand_account", None)
    )
    _write_facets_run(paths.run_dir(FACETS_RUN), answers)
    return tmp_path


def test_build_items_rows_and_drops(world):
    rows, meta = items_mod.build_items(FACETS_RUN, SAMPLE, SNAP)
    by_id = {r["comment_id"]: r for r in rows}
    assert sorted(by_id) == [BASE + 1, BASE + 2, BASE + 3]
    assert by_id[BASE + 1]["pain_sentence"] == "first s1"
    assert by_id[BASE + 1]["sentences"] == ["first s0", "first s1"]
    assert by_id[BASE + 1]["phase"] == "pos" and by_id[BASE + 1]["half"] == "explore"
    assert by_id[BASE + 1]["weight"] == 10.0
    assert by_id[BASE + 1]["domain"] == "work_careers"
    assert by_id[BASE + 1]["severity"] == 2.0
    assert by_id[BASE + 3]["pain_sentence"] == "third s0"
    assert by_id[BASE + 3]["phase"] == "neg"
    # s9 is out of range for a one-sentence comment; missing choice dropped too.
    assert meta["dropped_missing_pain"] == 2


def test_build_items_meta_counts_per_phase_and_account_type(world):
    _rows, meta = items_mod.build_items(FACETS_RUN, SAMPLE, SNAP)
    assert meta["answered_in_sample"] == 6
    assert meta["kept"] == 3
    # Counts cover every answered sample row, including rows later dropped
    # for a missing or out-of-range pain_sentence choice.
    assert meta["counts"]["pos"]["firsthand_account"] == 4
    assert meta["counts"]["pos"]["general_opinion"] == 1
    assert meta["counts"]["neg"]["firsthand_account"] == 1


def test_build_items_account_type_filter(world):
    rows, _meta = items_mod.build_items(
        FACETS_RUN, SAMPLE, SNAP,
        account_types=("firsthand_account", "general_opinion"),
    )
    assert BASE + 5 in {r["comment_id"] for r in rows}


def test_draft_sample_reproducible_and_weighted(world):
    rows, _meta = items_mod.build_items(FACETS_RUN, SAMPLE, SNAP)
    # Pool = pos + explore only: BASE+1 (w10), BASE+5 excluded by account
    # type; BASE+4 dropped earlier; so pool is just BASE+1.
    picked = items_mod.draft_sample(rows, 1, seed=20261001)
    assert [r["comment_id"] for r in picked] == [BASE + 1]
    again = items_mod.draft_sample(rows, 1, seed=20261001)
    assert [r["comment_id"] for r in again] == [BASE + 1]


def test_draft_sample_uses_reference_rng(tmp_path):
    """Same pool/order/pick math as the scratch script: rng.choice on the
    comment_id-ordered pool with p = w / w.sum()."""
    items = [
        {
            "comment_id": BASE + 10 + i,
            "pain_sentence": f"pain {i}",
            "sentences": [f"pain {i}"],
            "phase": "pos",
            "half": "explore",
            "weight": w,
            "domain": None,
            "severity": None,
        }
        for i, w in enumerate([5.0, 1.0, 9.0, 2.0])
    ]
    picked = items_mod.draft_sample(items, 2, seed=7)
    import numpy as np

    pool = [r for r in items if r["phase"] == "pos" and r["half"] == "explore"]
    w = np.array([r["weight"] for r in pool])
    expected = np.random.default_rng(7).choice(
        len(pool), 2, replace=False, p=w / w.sum()
    )
    assert [r["comment_id"] for r in picked] == [
        pool[int(j)]["comment_id"] for j in sorted(expected)
    ]


def test_draft_sample_filters_half_and_phase():
    items = [
        {"comment_id": BASE + 20, "pain_sentence": "p", "sentences": ["p"],
         "phase": "pos", "half": "confirm", "weight": 1.0,
         "domain": None, "severity": None},
        {"comment_id": BASE + 21, "pain_sentence": "q", "sentences": ["q"],
         "phase": "neg", "half": "explore", "weight": 1.0,
         "domain": None, "severity": None},
    ]
    with pytest.raises(ValueError):
        items_mod.draft_sample(items, 1, seed=1)  # empty pool


def test_cards_items_command_writes_parquet_and_meta(
    world, tmp_path, monkeypatch, capsys
):
    out = tmp_path / "out" / "items.parquet"
    args = cli.build_parser().parse_args(
        [
            "cards", "items",
            "--facets-run", FACETS_RUN,
            "--sample", SAMPLE,
            "--snapshot", SNAP,
            "--out", str(out),
        ]
    )
    args.func(args)
    table = pq.read_table(out)
    assert table.column_names[:3] == ["comment_id", "pain_sentence", "sentences"]
    got = {r["comment_id"]: r["pain_sentence"] for r in table.to_pylist()}
    assert got == {
        BASE + 1: "first s1",
        BASE + 2: "second s0",
        BASE + 3: "third s0",
    }
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    assert meta["kept"] == 3 and meta["dropped_missing_pain"] == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["rows"] == 3


def test_cards_draft_sample_command(world, tmp_path, monkeypatch, capsys):
    items_path = tmp_path / "items.parquet"
    rows, _meta = items_mod.build_items(FACETS_RUN, SAMPLE, SNAP)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=items_mod.ITEMS_SCHEMA),
        str(items_path),
    )
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    out = paths.DATA / "draft.tsv"
    args = cli.build_parser().parse_args(
        [
            "cards", "draft-sample",
            "--items", str(items_path),
            "--sample", SAMPLE,
            "--n", "1",
            "--seed", "5",
            "--out", str(out),
        ]
    )
    args.func(args)
    lines = out.read_text().splitlines()
    assert len(lines) == 1
    cid, domain, sev, pain = lines[0].split("\t")
    assert int(cid) == BASE + 1 and pain == "first s1"
    assert domain == "work_careers" and float(sev) == 2.0


def test_cards_draft_sample_refuses_outside_data(world, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "EXPORTS", tmp_path / "exports")
    args = cli.build_parser().parse_args(
        [
            "cards", "draft-sample",
            "--items", str(tmp_path / "items.parquet"),
            "--sample", SAMPLE,
            "--out", str(tmp_path / "elsewhere" / "draft.tsv"),
        ]
    )
    with pytest.raises(SystemExit):
        args.func(args)
    assert not (tmp_path / "elsewhere").exists()

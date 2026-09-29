"""Task 25.1: paraphrased question sets, `screen run --question-set`, and the
optional `assign` instruction kwargs.

Paraphrase sets keep the question IDs, types, and criteria keys of screen.v1
while rewording instructions and criteria text. The two engine hooks default to
the current wording so existing runs are byte-identical.
"""

import asyncio
import json

from atlas import paths
from atlas.cards.engine import assign as assign_mod
from atlas.cards.engine.assign import assign
from atlas.cards.engine.cardset import load_cardset
from atlas.inference.questions import load_question_set
from tests.cards.test_engine_support import make_ctx, make_transport
from tests.pilot.test_support import pilot_repo  # noqa: F401

ROOT = paths.ROOT


def _shape(qs):
    """(question ids, types, criteria keys, null-valued criteria) per set."""
    out = {}
    for qid, q in qs.questions.items():
        crit = q.get("criteria") or {}
        out[qid] = {
            "type": q["type"],
            "criteria_keys": set(crit),
            "nulls": {k for k, v in crit.items() if v is None},
        }
    return out


def _wording(qs):
    out = {}
    for qid, q in qs.questions.items():
        crit = {k: v for k, v in (q.get("criteria") or {}).items()}
        out[qid] = {"instructions": q["instructions"], "criteria": crit}
    return out


def test_paraphrase_sets_match_shape_and_differ_in_wording():
    base = load_question_set("screen", 1)
    for name in ("screen_para1", "screen_para2"):
        para = load_question_set(name, 1)
        assert para.label == f"{name}@1"
        assert para.state_fields == base.state_fields
        assert _shape(para) == _shape(base)
        assert _wording(para) != _wording(base)
        for qid in base.questions:
            assert (
                para.questions[qid]["instructions"]
                != base.questions[qid]["instructions"]
            )
    # The two paraphrases differ from each other, not only from the original.
    p1 = _wording(load_question_set("screen_para1", 1))
    p2 = _wording(load_question_set("screen_para2", 1))
    assert p1 != p2


def test_cards_paraphrases_config():
    path = paths.CONFIGS / "cards" / "paraphrases.v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    paras = data["paraphrases"]
    assert set(paras) == {"1", "2"}
    for pair in paras.values():
        assert set(pair) == {"group_instructions", "card_instructions"}
        assert pair["group_instructions"] != assign_mod.GROUP_INSTRUCTIONS
        assert pair["card_instructions"] != assign_mod.CARD_INSTRUCTIONS
        for field in pair.values():
            assert "`problem`" in field
        assert "`sentences`" in pair["group_instructions"]
        assert "`sentences`" not in pair["card_instructions"]
    assert paras["1"] != paras["2"]


def test_screen_run_question_set_option():
    """`screen run` accepts --question-set <name@version>, default screen@1."""
    import argparse

    from atlas.screen import cli as screen_cli

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    screen_cli.register(sub)
    args = parser.parse_args(["screen", "run", "--sample", "s", "--run", "r"])
    assert args.question_set == "screen@1"
    args = parser.parse_args(
        [
            "screen",
            "run",
            "--sample",
            "s",
            "--run",
            "r",
            "--question-set",
            "screen_para1@1",
        ]
    )
    assert args.question_set == "screen_para1@1"


def test_screen_run_dispatches_paraphrase_wording(
    pilot_repo, monkeypatch, capsys  # noqa: F811
):
    """A --question-set run packs the paraphrase wording and labels the run
    packed-screen_para1@1; the default run label is unchanged."""
    from atlas import paths
    from atlas.inference import ratelimit
    from atlas.screen import run
    from tests.pilot.test_support import make_transport, mock_env
    from tests.screen import support

    sid, _ids = support.write_sample(n=10)
    seen = []
    mock_env(monkeypatch, make_transport(seen=seen))
    clock = support.FakeClock()
    monkeypatch.setattr(ratelimit, "_clock", clock.now)
    monkeypatch.setattr(ratelimit, "_sleep", clock.sleep)
    out = run.screen_sample(
        sid, "para-r1", k=5, budget="screen", chunk=10, yes=True,
        question_set="screen_para1@1",
    )
    assert out["dispatched"] is True
    base = load_question_set("screen_para1", 1)
    para_text = base.questions["firsthand_problem"]["instructions"]
    for request in seen:
        for q in json.loads(request.content)["questions"].values():
            assert para_text.split("`comment`")[0][:20] in q["instructions"]
    params = json.loads(
        (paths.run_dir("para-r1") / "screen.json").read_text()
    )
    assert params["question_set"] == "packed-screen_para1@1"
    manifest = json.loads(
        (paths.run_dir("para-r1") / "run_manifest.json").read_text()
    )
    assert [e["label"] for e in manifest["question_sets"]] == [
        "packed-screen_para1@1"
    ]
    capsys.readouterr()


def test_assign_default_instructions_unchanged(tmp_path):
    """Omitting the new kwargs reproduces the current requests exactly."""
    cs = load_cardset("example", "t0")
    seen = []
    ctx = make_ctx(tmp_path, make_transport(seen=seen))
    rows = [
        {
            "comment_id": 9_000_000_701,
            "pain_sentence": "p",
            "sentences": ["p"],
        }
    ]
    asyncio.run(assign(ctx, rows, cs))
    body = json.loads(seen[0].content)
    assert (
        body["questions"]["group"]["instructions"]
        == assign_mod.GROUP_INSTRUCTIONS
    )


def test_assign_instruction_overrides(tmp_path):
    cs = load_cardset("example", "t0")
    seen = []
    ctx = make_ctx(tmp_path, make_transport(seen=seen))
    rows = [
        {
            "comment_id": 9_000_000_702,
            "pain_sentence": "p",
            "sentences": ["p"],
        }
    ]
    asyncio.run(
        assign(
            ctx,
            rows,
            cs,
            question_set_prefix="assign-para1",
            group_instructions="GI-PARA",
            card_instructions="CI-PARA",
        )
    )
    bodies = [json.loads(r.content) for r in seen]
    assert bodies[0]["questions"]["group"]["instructions"] == "GI-PARA"
    assert bodies[1]["questions"]["card"]["instructions"] == "CI-PARA"
    labels = {
        json.loads(line)["question_set"]
        for line in (tmp_path / "r1" / "done.jsonl").read_text().splitlines()
    }
    assert labels == {"assign-para1-g@t0", "assign-para1-c@t0"}

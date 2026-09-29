"""``site data --replies-run``: findings gain ``unsolved_rate`` from the
replies run's ``unsolved_by_problem.parquet``; without the flag the column is
still written, all null.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.cards.replies import UNSOLVED
from tests.sitedata.world import build, build_world, read


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def _assigned_card(world) -> dict[int, str]:
    """comment_id -> card for firsthand pos comments assigned with card_p >= 0.5."""
    assigned = {
        r["comment_id"]: r["card_id"]
        for r in pq.read_table(
            paths.run_dir("assign-syn") / "assignments-t9.parquet"
        ).to_pylist()
    }
    out = {}
    for cid, f in world["facet"].items():
        if (
            f["phase"] == "pos"
            and world["account"][cid] == "firsthand_account"
            and (assigned.get(cid) or "none") not in (None, "none")
        ):
            out[cid] = assigned[cid]
    return out


def _write_replies(run_id: str, rows: list[dict]) -> None:
    d = paths.run_dir(run_id) / "replies"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=UNSOLVED),
        d / "unsolved_by_problem.parquet",
    )


def _reply(cid, solved_p):
    return {
        "comment_id": cid,
        "n_replies": 2,
        "any_solution_named": solved_p >= 0.5,
        "solution_kinds": ["tool"] if solved_p >= 0.5 else [],
        "author_says_solved": "solved" if solved_p >= 0.5 else "still_unsolved",
        "unsolved": solved_p < 0.5,
        "solved_p": solved_p,
    }


def test_findings_unsolved_rate_null_without_replies_run(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    findings = read(out, "findings")
    assert findings
    assert all(r["unsolved_rate"] is None for r in findings)


def test_findings_carry_unsolved_rate_when_replies_run_given(world, tmp_path):
    cards = _assigned_card(world)
    by_card = {}
    for cid, card in sorted(cards.items()):
        by_card.setdefault(card, []).append(cid)
    assert set(by_card) == {"c01", "c02", "c03", "c04"}

    rows = []
    expected = {}
    # c01: every replied comment is unsolved. c02: all solved.
    # c03: half and half. c04 gets no replies, so its rate stays null.
    for card, ps in (
        ("c01", [0.0] * 4),
        ("c02", [1.0] * 4),
        ("c03", [1.0, 1.0, 0.0, 0.0]),
    ):
        for cid, p in zip(by_card[card], ps):
            rows.append(_reply(cid, p))
        expected[card] = sum(1.0 for p in ps if p < 0.5) / len(ps)
    _write_replies("replies-syn", rows)

    out = tmp_path / "site-real"
    build(out, replies_run="replies-syn")
    findings = {r["finding_id"]: r for r in read(out, "findings")}
    for card, want in expected.items():
        got = findings[card]["unsolved_rate"]
        assert got == pytest.approx(want)
    assert findings["c04"]["unsolved_rate"] is None
    assert findings["c01"]["unsolved_rate"] == 1.0
    assert findings["c02"]["unsolved_rate"] == 0.0

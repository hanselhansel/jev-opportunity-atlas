"""Two-phase estimation in the site data.

The facet sample is the second phase: pos rows drawn above the screen cutoff
plus a neg check slice, each weighted w1 / p2. Everything downstream of the
screen (evidence, card metrics, findings, domain_share) uses that weight and
the ``screen_positive`` population (pos rows only); neg rows never enter.
"""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from atlas import paths
from tests.sitedata.world import DOMAINS, TV, build, build_world, read

FA = "firsthand_account"


@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def _assigned() -> dict:
    run = paths.run_dir("assign-syn")
    return {
        r["comment_id"]: r
        for r in pq.read_table(run / f"assignments-{TV}.parquet").to_pylist()
    }


def test_neg_rows_are_faceted_and_assigned_but_never_published(world, tmp_path):
    """Guard the test world itself: neg rows really are in the saved runs."""
    neg = set(world["neg"])
    assert neg
    assert neg <= set(world["account"])
    assert neg & set(_assigned())
    out = tmp_path / "site-real"
    build(out)
    ev = {r["comment_id"]: r for r in read(out, "evidence")}
    assert not (set(ev) & neg)
    fe = read(out, "finding_evidence")
    assert not ({r["comment_id"] for r in fe} & neg)


def test_evidence_uses_phase2_weight_not_w1(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    for r in read(out, "evidence"):
        f = world["facet"][r["comment_id"]]
        assert f["phase"] == "pos"
        assert r["weight"] == pytest.approx(f["weight"])
        assert r["weight"] != pytest.approx(f["w1"])


def test_findings_count_only_pos_members(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    pos = set(world["pos"])
    expect = {}
    for cid, a in _assigned().items():
        if cid not in pos:
            continue
        if a["card_id"] in (None, "none") or (a["card_p"] or 0.0) < 0.5:
            continue
        expect[a["card_id"]] = expect.get(a["card_id"], 0) + 1
    findings = read(out, "findings")
    assert findings
    for f in findings:
        assert f["n_comments"] == expect.get(f["finding_id"], 0)


def test_domain_share_weights_and_firsthand_restriction(world, tmp_path):
    """Numerator and denominator: phase-2 pos rows, weight = w1/p2, firsthand."""
    out = tmp_path / "site-real"
    build(out, label_sets=())
    facet, account, domain, period = (
        world["facet"],
        world["account"],
        world["domain"],
        world["period"],
    )
    fh_ids = [c for c in world["pos"] if account[c] == FA]
    assert set(world["secondhand"]) <= set(world["pos"])
    rows = read(out, "domain_share")
    for p in ("all", "P01", "P07"):
        sub = [c for c in fh_ids if p == "all" or period[c] == p]
        total = sum(facet[c]["weight"] for c in sub)
        for d in DOMAINS:
            expect = sum(facet[c]["weight"] for c in sub if domain[c] == d) / total
            got = next(r for r in rows if r["period"] == p and r["domain"] == d)
            assert got["weighted_share"] == pytest.approx(expect)
            assert got["n"] == sum(1 for c in sub if domain[c] == d)
    # Counting the secondhand comments (which also carry domain answers) would
    # give different shares; the published numbers exclude them.
    pos = world["pos"]
    tot_all = sum(facet[c]["weight"] for c in pos)
    d = DOMAINS[0]
    exp_all = sum(facet[c]["weight"] for c in pos if domain[c] == d) / tot_all
    got = next(r for r in rows if r["period"] == "all" and r["domain"] == d)
    assert got["weighted_share"] != pytest.approx(exp_all)


def test_domain_share_denominator_names_firsthand_problems(world, tmp_path):
    out = tmp_path / "site-real"
    build(out, label_sets=())
    n_fh = sum(1 for c in world["pos"] if world["account"][c] == FA)
    for r in read(out, "domain_share"):
        if r["period"] == "all":
            assert f"{n_fh:,}" in r["denominator"]
            assert "firsthand" in r["denominator"]


def test_site_data_cli_requires_facet_sample():
    from atlas import cli as atlas_cli

    with pytest.raises(SystemExit):
        atlas_cli.build_parser().parse_args(
            [
                "site",
                "data",
                "--screen-run",
                "x",
                "--facets-run",
                "y",
                "--assign-run",
                "z",
                "--taxonomy",
                TV,
            ]
        )

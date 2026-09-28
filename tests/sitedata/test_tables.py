import pyarrow.parquet as pq

from atlas.sitedata.fixtures import fixture_tables
from atlas.sitedata.tables import BADGES, LANES, SITE_TABLES, write_fixtures


def test_fixtures_match_contract_and_are_marked_fictional(tmp_path):
    write_fixtures(tmp_path, seed=0)
    for name, schema in SITE_TABLES.items():
        t = pq.read_table(tmp_path / f"{name}.parquet")
        assert t.schema.equals(schema), name
    meta = dict(zip(*pq.read_table(tmp_path / "meta.parquet").to_pydict().values()))
    assert meta["mode"] == "fixture"


def test_fixtures_are_deterministic(tmp_path):
    write_fixtures(tmp_path / "a", seed=0)
    write_fixtures(tmp_path / "b", seed=0)
    for name in SITE_TABLES:
        assert (tmp_path / "a" / f"{name}.parquet").read_bytes() == (
            tmp_path / "b" / f"{name}.parquet"
        ).read_bytes()


def test_evidence_ids_and_shape(tmp_path):
    write_fixtures(tmp_path, seed=0)
    ev = pq.read_table(tmp_path / "evidence.parquet").to_pydict()
    assert ev["comment_id"] and len(ev["comment_id"]) == 400
    assert min(ev["comment_id"]) >= 9_000_000_000
    assert min(ev["story_id"]) >= 9_000_000_000
    assert len(set(ev["domain"])) == 8
    assert set(ev["domain"]) == {f"Domain {c}" for c in "ABCDEFGH"}
    assert set(ev["lane"]) == set(LANES)


def test_badges_are_known_values(tmp_path):
    write_fixtures(tmp_path, seed=0)
    ds = pq.read_table(tmp_path / "domain_share.parquet").to_pydict()
    assert set(ds["badge"]) <= set(BADGES)
    assert set(ds["lane"]) == set(LANES)
    # One window-total row per (lane, domain).
    period_all = [p for p in ds["period"] if p == "all"]
    assert len(period_all) == 2 * 8


def test_findings_statuses_and_finding_evidence_consistency(tmp_path):
    write_fixtures(tmp_path, seed=0)
    f = pq.read_table(tmp_path / "findings.parquet").to_pydict()
    assert set(f["status"]) == {"candidate", "validated"}
    fe = pq.read_table(tmp_path / "finding_evidence.parquet").to_pydict()
    ev_ids = set(pq.read_table(tmp_path / "evidence.parquet").to_pydict()["comment_id"])
    assert set(fe["comment_id"]) <= ev_ids
    assert set(fe["role"]) <= {"supporting", "contradicting"}
    for i, fid in enumerate(f["finding_id"]):
        rows = [j for j, x in enumerate(fe["finding_id"]) if x == fid]
        assert len(rows) == f["n_comments"][i]
        contra = [j for j in rows if fe["role"][j] == "contradicting"]
        assert len(contra) == f["contradicting_n"][i]


def test_breadth_shares_sum_to_one_per_period():
    rows = fixture_tables(0)["domain_share"].to_pylist()
    breadth = [r for r in rows if r["lane"] == "breadth"]
    by_period = {}
    for r in breadth:
        by_period.setdefault(r["period"], []).append(r)
    for period_rows in by_period.values():
        assert len(period_rows) == 8
        shares = [r["weighted_share"] for r in period_rows]
        assert all(s is not None for s in shares)
        assert abs(sum(shares) - 1) < 1e-9
        total = f"{sum(r['n'] for r in period_rows):,}"
        for r in period_rows:
            assert total in r["denominator"]
    for r in rows:
        if r["lane"] == "discovery":
            assert r["weighted_share"] is None


def test_breadth_intervals_bracket_the_share():
    rows = fixture_tables(0)["domain_share"].to_pylist()
    for r in rows:
        if r["lane"] == "breadth" and not r["too_few"]:
            assert r["ci_low"] <= r["weighted_share"] <= r["ci_high"]


def test_no_text_or_author_columns():
    banned = {"text", "comment", "author", "username", "by"}
    for name, schema in SITE_TABLES.items():
        assert not banned & set(schema.names), name

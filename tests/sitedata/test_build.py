"""Site tables built from saved (synthetic) run directories. No Jev calls."""

from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from atlas import paths
from atlas.publication.export import text_gate
from atlas.sitedata.tables import SITE_TABLES
from tests.sitedata.world import CARDS, DOMAINS, TV, build, build_world, read

UNAUDITED = "as classified by Jev; unaudited"
EXTRA_COLUMNS = {
    "domain_share": ["qualifier"],
    "quality": ["system"],
    "findings": ["unsolved_rate"],
}

@pytest.fixture
def world(tmp_path, monkeypatch):
    return build_world(tmp_path / "repo", monkeypatch)


def test_writes_every_site_table_with_contract_columns(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    for name, schema in SITE_TABLES.items():
        got = pq.read_schema(out / f"{name}.parquet")
        n = len(schema)
        assert pa.schema(list(got)[:n]).equals(schema), name
        assert got.names[n:] == EXTRA_COLUMNS.get(name, []), name
    meta = {r["key"]: r["value"] for r in read(out, "meta")}
    assert meta["mode"] == "real"
    assert meta["snapshot_id"] == "snap-syn"
    assert meta["run_id"] == "screen-syn"
    assert meta["facets_run"] == "facets-syn"
    assert meta["assign_run"] == "assign-syn"
    assert meta["facet_sample"] == "facet-syn"
    assert meta["window_start"] == "2025-09-28T00:00:00Z"
    assert meta["window_end"] == "2026-09-28T00:00:00Z"
    assert meta["built_at"] == "2026-09-29T12:00:00Z"
    assert "code_commit" in meta
    assert read(out, "coverage") == read(paths.snapshot_dir("snap-syn"), "coverage")


def test_domain_share_is_ppi_corrected_with_gold(world, tmp_path):
    from atlas.estimation.ppi import ppi_ratio

    out = tmp_path / "site-real"
    build(out)
    rows = [r for r in read(out, "domain_share") if r["period"] == "all"]
    assert {r["domain"] for r in rows} == set(DOMAINS)
    for r in rows:
        assert r["lane"] == "breadth" and r["badge"] == "estimated"
        assert r["qualifier"].startswith("PPI-corrected")
        assert r["ci_low"] <= r["weighted_share"] <= r["ci_high"]
        assert r["n"] == sum(
            1
            for c in world["pos"]
            if world["account"][c] == "firsthand_account"
            and world["domain"][c] == r["domain"]
        )
        assert "firsthand" in r["denominator"] and len(r["denominator"]) <= 80
    # Same numbers as calling the estimator directly on the saved files: the
    # numerator and denominator are PPI means over phase-2 pos rows, weighted
    # by the phase-2 weight and restricted to firsthand problems.
    facet = world["facet"]
    sub = [c for c in facet if facet[c]["phase"] == "pos"]
    fa = {c for c in sub if world["account"][c] == "firsthand_account"}
    d = DOMAINS[0]
    gold = [c for c in world["gold"] if c in set(sub)]
    labels = [
        json.loads(x) for x in (paths.LABELS / "labels.jsonl").read_text().splitlines()
    ]
    fh_y = {
        r["comment_id"]: r["value"] == "yes"
        for r in labels
        if r["question_id"] == "firsthand_problem"
    }
    dom_y = {
        r["comment_id"]: r["value"] for r in labels if r["question_id"] == "domain"
    }
    num_hat = [float(c in fa and world["domain"][c] == d) for c in sub]
    den_hat = [float(c in fa) for c in sub]
    res = ppi_ratio(
        (
            num_hat,
            [float(fh_y[c] and dom_y.get(c) == d) for c in gold],
            [float(c in fa and world["domain"][c] == d) for c in gold],
        ),
        (
            den_hat,
            [float(fh_y[c]) for c in gold],
            [float(c in fa) for c in gold],
        ),
        w_all=[facet[c]["weight"] for c in sub],
        w_gold=[facet[c]["weight"] for c in gold],
        sel_prob_gold=[0.25] * len(gold),
        strata_all=[facet[c]["stratum"] for c in sub],
        strata_gold=[facet[c]["stratum"] for c in gold],
        clusters_all=[facet[c]["story_id"] for c in sub],
        clusters_gold=[facet[c]["story_id"] for c in gold],
        n_boot=200,
        seed=0,
    )
    got = next(r for r in rows if r["domain"] == d)
    assert got["weighted_share"] == pytest.approx(res["estimate"])


def test_domain_share_without_gold_is_marked_unaudited(world, tmp_path):
    out = tmp_path / "site-real"
    build(out, label_sets=())
    rows = read(out, "domain_share")
    assert {r["period"] for r in rows} == {f"P{i:02d}" for i in range(1, 13)} | {"all"}
    for r in rows:
        assert r["badge"] == "estimated" and r["qualifier"] == UNAUDITED
        if r["too_few"]:
            assert r["ci_low"] is None and r["ci_high"] is None
        else:
            assert r["ci_low"] <= r["weighted_share"] <= r["ci_high"]
    for p in {r["period"] for r in rows}:
        shares = [r["weighted_share"] for r in rows if r["period"] == p]
        assert sum(shares) == pytest.approx(1.0)


def test_evidence_has_ids_labels_probabilities_and_hashes_only(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    ev = read(out, "evidence")
    snap = {r["id"]: r for r in read(paths.snapshot_dir("snap-syn"), "comments")}
    assert {r["comment_id"] for r in ev} == set(world["faceted"])
    gold = set(world["gold"])
    for r in ev:
        c = r["comment_id"]
        assert c >= 9_000_000_000 and r["story_id"] >= 9_000_000_000
        assert r["text_sha256"] == snap[c]["text_sha256"]
        assert r["domain"] == world["domain"][c]
        assert json.loads(r["probabilities_json"])[r["domain"]] == 0.8
        assert r["run_id"] == "facets-syn" and r["taxonomy_version"] == TV
        assert (r["human_label"] is not None) == (c in gold)
        assert r["weight"] == pytest.approx(world["facet"][c]["weight"])
        assert 0.0 <= r["evidence_strength"] <= 1.0
    blob = b"".join(p.read_bytes() for p in out.iterdir())
    assert b"synthetic comment body" not in blob and b"u14" not in blob


def test_findings_come_from_card_metrics_and_ranking(world, tmp_path):
    from atlas.cards.metrics import card_metrics

    out = tmp_path / "site-real"
    build(out)
    findings = read(out, "findings")
    fe = read(out, "finding_evidence")
    assert [f["finding_id"] for f in findings] and {
        f["finding_id"] for f in findings
    } <= set(CARDS)
    ev_ids = {r["comment_id"] for r in read(out, "evidence")}
    assert {r["comment_id"] for r in fe} <= ev_ids
    run = paths.run_dir("assign-syn")
    snap = pq.read_table(paths.snapshot_dir("snap-syn") / "comments.parquet")
    pos = pa.array(sorted(world["pos"]))
    assignments = pq.read_table(run / f"assignments-{TV}.parquet").filter(
        pc.is_in(pc.field("comment_id"), value_set=pos)
    )
    metrics = {
        r["card_id"]: r
        for r in card_metrics(
            assignments,
            pq.read_table(paths.run_dir("facets-syn") / "answers" / "part-0.parquet"),
            snap,
            None,
        ).to_pylist()
    }
    for f in findings:
        m = metrics[f["finding_id"]]
        assert f["n_authors"] == m["n_authors"] and f["n_threads"] == m["n_threads"]
        assert f["status"] in ("validated", "candidate")
        assert (f["validated_at"] is not None) == (f["status"] == "validated")
        mine = [r for r in fe if r["finding_id"] == f["finding_id"]]
        assert len(mine) == f["n_comments"]
        assert sum(r["role"] == "contradicting" for r in mine) == f["contradicting_n"]
        assert f["contradicting"] == (f["contradicting_n"] > 0)
        assert f["problem_statement"].startswith("Synthetic need")


def test_runs_come_from_ledgers(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    runs = {r["run_id"]: r for r in read(out, "runs")}
    assert set(runs) == {"screen-syn", "facets-syn", "assign-syn", "bench-syn"}
    s = runs["screen-syn"]
    assert s["phase"] == "screen" and s["kind"] == "jev"
    assert s["calls"] == 120 and s["attempts"] == 132 and s["retries"] == 12
    assert s["unknown_attempts"] == 12 and s["cache_hits"] == 1
    assert s["calculated_usd"] == pytest.approx(0.12)
    assert s["p50_ms"] <= s["p95_ms"] and s["wall_s"] == pytest.approx(300.0)


def test_quality_has_system_and_synthetic_benchmark_rows(world, tmp_path):
    out = tmp_path / "site-real"
    build(out)
    q = read(out, "quality")
    audit = {
        (r["system"], r["metric"]): r for r in q if r["label_set"] == "assignment_audit"
    }
    assert audit[("jev", "precision_strict")]["value"] == 0.81
    assert audit[("jev", "precision_strict")]["n"] == 86
    assert audit[("random_card", "precision_strict")]["ci_high"] == 0.25
    bench = [r for r in q if r["label_set"] == "synthetic"]
    assert bench and all(r["system"] == "jev" for r in bench)
    assert {r["question_id"] for r in bench} >= {"firsthand_problem", "card_assignment"}


def test_every_output_passes_the_text_gate(world, tmp_path):
    from atlas.sitedata.build import CARD_TEXT_COLUMNS, _gate_copy, site_text_problems

    out = tmp_path / "site-real"
    build(out)
    assert site_text_problems(out) == []
    (tmp_path / "gate").mkdir()
    # The raw gate flags only the approved card-text columns of findings, which
    # the build checks value-by-value against the cardset.
    for p in text_gate(_gate_copy(out, tmp_path / "gate")):
        assert p.split()[2].split(":")[0] == "findings.parquet", p
        assert p.split()[2].split(":")[1] in CARD_TEXT_COLUMNS, p


def test_card_text_not_in_the_cardset_fails_the_gate(world, tmp_path):
    from atlas.sitedata.build import site_text_problems

    out = tmp_path / "site-real"
    build(out)
    t = pq.read_table(out / "findings.parquet")
    i = t.schema.get_field_index("title")
    t = t.set_column(i, "title", pa.array(["not an approved card"] * t.num_rows))
    pq.write_table(t, out / "findings.parquet")
    assert any("findings.parquet:title" in p for p in site_text_problems(out))


def test_site_data_cli_writes_real_tables(world, tmp_path, capsys):
    from atlas import cli as atlas_cli

    out = tmp_path / "data-real"
    args = atlas_cli.build_parser().parse_args(
        ["site", "data", "--out", str(out), "--snapshot", "snap-syn",
         "--screen-run", "screen-syn", "--facets-run", "facets-syn",
         "--assign-run", "assign-syn", "--taxonomy", TV,
         "--facet-sample", "facet-syn",
         "--label-set", "calibration", "--benchmark-run", "bench-syn",
         "--n-boot", "50"])
    args.func(args)
    meta = {r["key"]: r["value"] for r in read(out, "meta")}
    assert meta["mode"] == "real" and meta["label_sets"] == "calibration"
    assert json.loads(capsys.readouterr().out)["findings"] > 0

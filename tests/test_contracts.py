from atlas import contracts as c
from atlas import paths


def test_schemas_have_versions_and_required_fields():
    assert c.SCHEMA_VERSION == 1
    for name in [
        "id",
        "created_at",
        "period",
        "story_id",
        "text_norm",
        "sentences",
        "eligible",
        "text_sha256",
    ]:
        assert name in c.COMMENTS.names
    assert "text_html" not in c.COMMENTS.names  # raw shards keep HTML
    for name in ["comment_id", "stratum", "inclusion_prob", "weight", "batch"]:
        assert name in c.SAMPLE.names
    for name in [
        "run_id",
        "logical_call_id",
        "attempt",
        "request_id",
        "input_tokens",
        "cost_class",
    ]:
        assert name in c.LEDGER_FIELDS
    for name in [
        "comment_id",
        "question_id",
        "noul",
        "choice",
        "probabilities_json",
        "confidence",
    ]:
        assert name in c.ANSWERS.names
    assert c.COVERAGE.names == ["dimension", "key", "count"]
    assert "pending" in c.COST_CLASSES


def test_empty_tables_validate():
    for schema in [
        c.COMMENTS,
        c.STORIES,
        c.CONTEXT,
        c.COVERAGE,
        c.SAMPLE,
        c.ANSWERS,
        c.LABELS,
    ]:
        assert schema.empty_table().schema.equals(schema)


def test_paths_resolve_at_call_time(monkeypatch, tmp_path):
    assert paths.snapshot_dir("s1") == paths.ROOT / "data" / "snapshots" / "s1"
    assert paths.ledger_path("r1") == paths.ROOT / "runs" / "r1" / "ledger.jsonl"
    monkeypatch.setattr(paths, "SAMPLES", tmp_path)
    assert paths.sample_path("p1") == tmp_path / "p1.parquet"


def test_period_labels():
    start, end = 0, 1200
    assert c.period_of(0, start, end) == "P01"
    assert c.period_of(99, start, end) == "P01"
    assert c.period_of(100, start, end) == "P02"
    assert c.period_of(1199, start, end) == "P12"
    assert c.period_of(1200, start, end) is None
    assert c.period_of(-1, start, end) is None


def test_analysis_layer_contracts():
    for schema in [c.CARDS, c.ASSIGNMENTS, c.GOLD_DRAWS]:
        assert schema.empty_table().schema.equals(schema)
    assert "selection_prob" in c.GOLD_DRAWS.names
    halves = [c.half_of(i) for i in range(10_000)]
    assert c.half_of(12345) == c.half_of(12345)
    assert 0.47 < halves.count("explore") / len(halves) < 0.53

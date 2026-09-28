import json

import pytest

from atlas import contracts
from atlas.evaluation.store import LabelStore, allowed_values


def test_append_and_latest_wins(tmp_path):
    s = LabelStore(tmp_path / "labels.jsonl")
    s.add(comment_id=9_000_000_001, label_set="calibration", question_id="firsthand_problem", value="no",
          rubric_version="v1", reviewer="hansel", started_at="t0", ended_at="t1", seconds=12.0)
    s.add(comment_id=9_000_000_001, label_set="calibration", question_id="firsthand_problem", value="yes",
          rubric_version="v1", reviewer="hansel", started_at="t2", ended_at="t3", seconds=5.0)
    latest = s.latest("calibration")
    assert latest[(9_000_000_001, "firsthand_problem")]["value"] == "yes"
    assert len(s.all_rows()) == 2  # history kept


def test_rejects_unknown_value(tmp_path):
    s = LabelStore(tmp_path / "labels.jsonl")
    with pytest.raises(ValueError):
        s.add(comment_id=9_000_000_001, label_set="calibration", question_id="firsthand_problem", value="maybe",
              rubric_version="v1", reviewer="hansel", started_at="t0", ended_at="t1", seconds=1.0)


def test_row_schema_and_domain_values(tmp_path):
    s = LabelStore(tmp_path / "labels.jsonl")
    s.add(comment_id=9_000_000_001, label_set="calibration", question_id="domain",
          value="software_development", rubric_version="v1", reviewer="hansel",
          started_at="t0", ended_at="t1", seconds=1.0)
    row = json.loads((tmp_path / "labels.jsonl").read_text().splitlines()[0])
    assert list(row) == list(contracts.LABELS.names)
    assert row["comment_id"] == 9_000_000_001
    assert isinstance(row["seconds"], float)
    assert "software_development" in allowed_values()["domain"]
    with pytest.raises(ValueError):
        s.add(comment_id=9_000_000_002, label_set="calibration", question_id="domain",
              value="not_a_domain", rubric_version="v1", reviewer="hansel",
              started_at="t0", ended_at="t1", seconds=1.0)
    with pytest.raises(ValueError):
        s.add(comment_id=9_000_000_003, label_set="calibration", question_id="no_such_question",
              value="yes", rubric_version="v1", reviewer="hansel",
              started_at="t0", ended_at="t1", seconds=1.0)

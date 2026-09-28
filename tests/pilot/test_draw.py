"""Task 7.1: pilot draw over the v2 strata, idempotent and never overwriting."""

import hashlib
import json
import math
from collections import Counter

import numpy as np
import pyarrow.parquet as pq
import pytest

from atlas import contracts, paths
from tests.pilot.test_support import (  # noqa: F401
    EXPECTED_SIZES,
    SNAPSHOT_ID,
    pilot_repo,
)


def _frame_sizes():
    from atlas.sampling import design_v2

    sdir = paths.snapshot_dir(SNAPSHOT_ID)
    comments = pq.read_table(
        sdir / "comments.parquet",
        columns=[
            "id",
            "story_id",
            "period",
            "thread_type",
            "text_norm",
            "word_count",
            "eligible",
        ],
    )
    stories = pq.read_table(sdir / "stories.parquet", columns=["id", "thread_type"])
    frame = design_v2.build_frame_v2(comments, stories)
    labels = frame.column("stratum").to_numpy(zero_copy_only=False)
    uniq, counts = np.unique(labels, return_counts=True)
    return frame, {str(u): int(c) for u, c in zip(uniq, counts)}


def test_pilot_draw_formula_and_manifest(pilot_repo):  # noqa: F811
    from atlas.pilot.draw import pilot_draw
    from atlas.sampling import design_v2

    table = pilot_draw(SNAPSHOT_ID)
    assert table.schema == contracts.SAMPLE
    assert set(table.column("sample_id").to_pylist()) == {"pilot-20260929"}
    assert set(table.column("batch").to_pylist()) == {1}
    frame, sizes = _frame_sizes()
    assert sizes == EXPECTED_SIZES
    n = frame.num_rows
    counts = Counter(table.column("stratum").to_pylist())
    assert dict(counts) and set(counts) == set(sizes)
    for h, n_h in sizes.items():
        expected = min(n_h, max(20, round(2000 * n_h / n)))
        assert counts[h] == expected
        assert counts[h] >= min(n_h, 20)
    assert math.isclose(
        float(table.column("weight").to_numpy().sum()),
        float(n),
        rel_tol=1e-9,
    )
    rows = table.to_pylist()
    assert len({r["comment_id"] for r in rows}) == len(rows)
    for r in rows:
        assert r["inclusion_prob"] == pytest.approx(counts[r["stratum"]] / sizes[r["stratum"]])
        assert r["weight"] == pytest.approx(sizes[r["stratum"]] / counts[r["stratum"]])

    sidecar_path = paths.SAMPLES / "pilot-20260929.json"
    sidecar = json.loads(sidecar_path.read_text())
    assert sidecar["seed"] == 20260929
    assert sidecar["seeds_by_batch"] == {"1": 20260929}
    assert sidecar["n_target"] == 2000 and sidecar["min_per_stratum"] == 20
    assert sidecar["frame_snapshot_id"] == SNAPSHOT_ID
    assert sidecar["purpose"] == "pilot" and sidecar["design_version"] == "v2"
    design = sidecar["design"]
    assert design["pain_patterns_version"] == design_v2.PAIN_PATTERNS_VERSION
    assert design["rule"] == "min(N_h, max(min_per_stratum, round(n_target*N_h/N)))"
    assert design["allocation"] == dict(counts)
    assert design["N_h"] == sizes
    parquet = paths.sample_path("pilot-20260929")
    assert sidecar["sha256"] == hashlib.sha256(parquet.read_bytes()).hexdigest()
    assert (paths.MANIFESTS / "samples" / "pilot-20260929.json").exists()


def test_pilot_draw_idempotent_and_mismatched_params_raise(pilot_repo):  # noqa: F811
    from atlas.pilot.draw import pilot_draw

    table = pilot_draw(SNAPSHOT_ID, n_target=500, min_per_stratum=5, seed=3)
    again = pilot_draw(SNAPSHOT_ID, n_target=500, min_per_stratum=5, seed=3)
    assert again.to_pylist() == table.to_pylist()
    assert set(again.column("sample_id").to_pylist()) == {"pilot-3"}

    with pytest.raises(ValueError):
        pilot_draw(SNAPSHOT_ID, n_target=900, min_per_stratum=5, seed=3)
    with pytest.raises(ValueError):
        pilot_draw(SNAPSHOT_ID, n_target=500, min_per_stratum=7, seed=3)
    with pytest.raises(ValueError):
        pilot_draw("other-snapshot", n_target=500, min_per_stratum=5, seed=3)

    # A different seed draws under a different sample id, not an overwrite.
    other = pilot_draw(SNAPSHOT_ID, n_target=500, min_per_stratum=5, seed=4)
    assert set(other.column("sample_id").to_pylist()) == {"pilot-4"}
    assert paths.sample_path("pilot-4").exists()

import os
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import pytest

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / "site"

pytestmark = pytest.mark.skipif(
    shutil.which("npm") is None or not (SITE / "node_modules").is_dir(),
    reason="site dependencies not installed",
)


def _build_env(extra=None):
    # Drop any inherited ATLAS_SITE_* so the ambient environment cannot leak in.
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_SITE_")}
    env.update(extra or {})
    return env


def test_build_has_no_secrets_and_emits_fixture_mode():
    subprocess.run(
        ["npm", "run", "build"],
        cwd=SITE,
        check=True,
        capture_output=True,
        env=_build_env(),
    )
    dist = SITE / "dist"
    blob = "".join(
        p.read_text(errors="ignore")
        for p in dist.rglob("*")
        if p.is_file() and p.suffix in {".html", ".js", ".json", ".css"}
    )
    assert "api.typesafe.ai" not in blob
    assert "apikey_" not in blob
    assert "FICTIONAL DATA" in blob
    metas = sorted((dist / "_file" / "data").glob("meta*.parquet"))
    assert metas, "meta parquet missing from build output"
    meta = pq.read_table(metas[0]).to_pydict()
    assert dict(zip(meta["key"], meta["value"]))["mode"] == "fixture"


def test_production_build_fails_without_data():
    r = subprocess.run(
        ["npm", "run", "build"],
        cwd=SITE,
        check=False,
        capture_output=True,
        env=_build_env({"ATLAS_SITE_MODE": "production"}),
    )
    assert r.returncode != 0

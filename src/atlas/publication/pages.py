"""Publish the built site or essay to a `gh-pages` branch (no GitHub Actions here).

For ``kind="site"`` (the default) `publish_pages` refuses unless the built data
says `meta.mode == "real"` and passes the text gate. For ``kind="essay"`` it
refuses unless the `story dist` output is present and `data/story.json` passes
`story check`. Either way it copies the build into a temporary, detached,
no-checkout git worktree, adds `.nojekyll`, scans the result with the release
secret scanner and gitleaks, and writes an orphan (or gh-pages-parented) commit
with `commit-tree`. Nothing moves a ref or pushes unless `dry_run=False`, which
only the main session uses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Repository-selecting variables (set inside git hooks, for example) would make
# the git calls below act on some other repository than `repo_root`.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
)


class PagesError(Exception):
    pass


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise PagesError(f"git {args[0]} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def _tip(repo: Path, branch: str, remote: str) -> str | None:
    for ref in (f"refs/heads/{branch}", f"refs/remotes/{remote}/{branch}"):
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=repo,
            env=_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    return None


def _site_data_problems(data_dir: Path) -> list[str]:
    """Text gate on the built site's data, honoring approved card text.

    Framework writes hashed names (findings.576b33fc.parquet); copy them back to
    plain names so ``site_text_problems`` can apply its approved-card exemption.
    """
    import re
    import shutil
    import tempfile

    from atlas.sitedata.build import site_text_problems

    with tempfile.TemporaryDirectory() as tmp:
        for f in sorted(data_dir.glob("*.parquet")):
            plain = re.sub(r"\.[0-9a-f]{8}\.parquet$", ".parquet", f.name)
            shutil.copy(f, Path(tmp) / plain)
        if (Path(tmp) / "findings.parquet").exists():
            return site_text_problems(tmp)
        from atlas.publication.allowlist import text_gate

        return text_gate(Path(tmp))  # no findings, so no card text to exempt


def _check_data(dist: Path) -> None:
    import pyarrow.parquet as pq

    metas = sorted((dist / "_file" / "data").glob("meta*.parquet"))
    if not metas:
        raise PagesError(
            f"{dist} has no _file/data/meta*.parquet; build the site first"
        )
    for m in metas:
        t = pq.read_table(m).to_pydict()
        mode = dict(zip(t.get("key", []), t.get("value", []))).get("mode")
        if mode != "real":
            raise PagesError(f"pages need meta.mode == real, found {mode!r}")
    problems = _site_data_problems(dist / "_file" / "data")
    if problems:
        raise PagesError("text gate blocked the build:\n" + "\n".join(problems))


def _check_essay(dist: Path) -> None:
    """Essay gate: the files `story dist` ships, plus `story check` on the data."""
    from atlas.story.check import check_story

    for rel in ("index.html", "app.js", "data/story.json"):
        if not (dist / rel).is_file():
            raise PagesError(
                f"{dist} is missing {rel}; run `atlas story dist` first"
            )
    problems = check_story(dist / "data" / "story.json")
    if problems:
        raise PagesError(
            "story check blocked the build:\n" + "\n".join(problems)
        )


def _scan(tree: Path, repo: Path) -> None:
    from atlas.publication.allowlist import scan_release

    findings = [str(f) for f in scan_release(tree)]
    if findings:
        raise PagesError("secret scan blocked the build:\n" + "\n".join(findings))
    cmd = [
        "gitleaks",
        "dir",
        str(tree),
        "--redact",
        "--no-banner",
        "--log-level",
        "warn",
    ]
    cfg = repo / ".gitleaks.toml"
    if cfg.is_file():
        cmd += ["--config", str(cfg)]
    if subprocess.run(cmd, capture_output=True, check=False).returncode != 0:
        raise PagesError(
            "gitleaks blocked the build (run gitleaks dir on it to see why)"
        )


def publish_pages(
    dist_dir: Path,
    dry_run: bool = True,
    repo_root: Path | None = None,
    branch: str = "gh-pages",
    remote: str = "origin",
    kind: str = "site",
) -> dict:
    """Build the gh-pages commit for `dist_dir`; push it only when dry_run=False."""
    from atlas import paths

    dist = Path(dist_dir).resolve()
    repo = Path(repo_root) if repo_root else paths.ROOT
    if shutil.which("gitleaks") is None:
        raise PagesError("gitleaks is required to publish pages: brew install gitleaks")
    if kind == "essay":
        _check_essay(dist)
    elif kind == "site":
        _check_data(dist)
    else:
        raise PagesError(f"unknown pages kind {kind!r}")
    parent = _tip(repo, branch, remote)
    tmp = Path(tempfile.mkdtemp(prefix="atlas-pages-"))
    wt = tmp / "worktree"
    _git(
        repo, "worktree", "add", "--detach", "--no-checkout", str(wt), parent or "HEAD"
    )
    try:
        shutil.copytree(dist, wt, dirs_exist_ok=True)
        (wt / ".nojekyll").write_text("")
        _scan(wt, repo)
        _git(wt, "add", "--all", "--force", ".")
        tree = _git(wt, "write-tree")
        files = len(_git(wt, "ls-files").splitlines())
        args = ["commit-tree", tree, "-m", f"Publish atlas {kind}"]
        if parent:
            args[2:2] = ["-p", parent]
        commit = _git(wt, *args)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            cwd=repo,
            env=_env(),
            capture_output=True,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=repo,
            env=_env(),
            capture_output=True,
            check=False,
        )
    result = {
        "commit": commit,
        "tree": tree,
        "parent": parent,
        "branch": branch,
        "files": files,
        "dry_run": dry_run,
        "pushed": False,
    }
    if not dry_run:
        _git(repo, "push", remote, f"{commit}:refs/heads/{branch}")
        _git(repo, "update-ref", f"refs/heads/{branch}", commit)
        result["pushed"] = True
    return result

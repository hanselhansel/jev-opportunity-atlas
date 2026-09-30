"""``story dist``: copy the publishable essay tree into an output directory.

Only allowlisted paths ship — ``index.html``, ``app.js``, ``style.css``,
``charts/``, ``lib/``, ``content/story.md``, and ``data/story.json``.
``essay/test/``, ``essay/fixtures/``, and ``content/story.fixture.md`` never
leave the repo. The copied tree must pass ``story check`` on ``story.json``
and a privacy gate over every file: no URLs outside ``index.html``'s
importmap (cdn.jsdelivr.net only), no email addresses, no local absolute
paths, and no hits from the release secret scanner.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from atlas import paths

COPY_FILES = (
    "index.html",
    "app.js",
    "style.css",
    "content/story.md",
    "data/story.json",
)
COPY_DIRS = ("charts", "lib")

IMPORTMAP_HOST = "https://cdn.jsdelivr.net/"

_IMPORTMAP = re.compile(
    r"<script[^>]*type=[\"']importmap[\"'][^>]*>.*?</script>",
    re.DOTALL | re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s\"'<>)\]]+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LOCAL_PATH = re.compile(r"/Users/|/home/|[A-Za-z]:\\Users\\")


class DistError(Exception):
    pass


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _gate_file(path: Path, rel: str) -> list[str]:
    """Privacy problems in one file; findings carry file and line only."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    problems = []
    if rel == "index.html":
        for m in _IMPORTMAP.finditer(text):
            for u in _URL.finditer(m.group(0)):
                if not u.group(0).startswith(IMPORTMAP_HOST):
                    problems.append(
                        f"privacy-gate url {rel}:{_line(text, m.start())}"
                    )
        text = _IMPORTMAP.sub(lambda m: " " * len(m.group(0)), text)
    for rx, rule in ((_URL, "url"), (_EMAIL, "email"), (_LOCAL_PATH, "path")):
        for m in rx.finditer(text):
            problems.append(f"privacy-gate {rule} {rel}:{_line(text, m.start())}")
    return problems


def privacy_problems(tree: Path) -> list[str]:
    """The privacy gate over the copied tree, including the secret scanner."""
    from atlas.publication.secret_scan import scan_paths

    files = [p for p in sorted(tree.rglob("*")) if p.is_file()]
    problems = []
    for p in files:
        problems.extend(_gate_file(p, p.relative_to(tree).as_posix()))
    problems.extend(str(f) for f in scan_paths(files))
    return problems


def build_dist(out_dir: Path, essay_dir: Path | None = None) -> dict:
    """Copy the publishable essay files to ``out_dir`` and gate the result."""
    from atlas.story.check import check_story

    essay = Path(essay_dir) if essay_dir else paths.ROOT / "essay"
    out = Path(out_dir)
    missing = [rel for rel in COPY_FILES if not (essay / rel).is_file()]
    missing += [d for d in COPY_DIRS if not (essay / d).is_dir()]
    if missing:
        raise DistError(f"essay is missing: {', '.join(missing)}")
    if out.exists():
        if not out.is_dir():
            raise DistError(f"{out} exists and is not a directory")
        # only clear an empty dir or an earlier dist, never a repo or other tree
        prior = (out / "index.html").is_file() and (out / "data" / "story.json").is_file()
        if any(out.iterdir()) and (not prior or (out / ".git").exists()):
            raise DistError(f"{out} is not empty and is not an earlier essay dist")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel in COPY_FILES:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(essay / rel, dest)
    for d in COPY_DIRS:
        shutil.copytree(essay / d, out / d)

    problems = check_story(out / "data" / "story.json")
    if problems:
        raise DistError("story check failed:\n" + "\n".join(problems))
    problems = privacy_problems(out)
    if problems:
        raise DistError("privacy gate blocked the dist:\n" + "\n".join(problems))
    return {
        "out": str(out),
        "files": sum(1 for p in out.rglob("*") if p.is_file()),
    }

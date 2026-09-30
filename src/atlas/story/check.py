"""``story check``: prove no HN text or username can reach ``story.json``.

Every string value in the document must be drawn from the approved
vocabulary — card and group statements and short labels, domain and role
names, tool names from ``configs/tools.v1.yaml``, run ids, period and
quarter codes, fixed labels, the essay title — or match a structural pattern
(identifier, ISO timestamp, git sha). Dict keys are structural, except the
keys that would carry raw text; any key named ``text``, ``body``,
``author``, ``username``, or ``url`` is a failure wherever it appears.
``terms`` entries additionally must pass the S4 gate: at least 20 comments
and 10 distinct authors.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from atlas import paths

BANNED_KEYS = {"text", "body", "author", "username", "url"}
MIN_TERM_COMMENTS = 20
MIN_TERM_AUTHORS = 10

_IDENT = re.compile(r"(?:n|pc|gp|g|c|b|t|v)\d+")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}([T ][0-9:.+Z-]*)?")
_SHA = re.compile(r"[0-9a-f]{7,64}")


def _vocabulary(doc: dict) -> set:
    """The set of approved strings, assembled from configs and the doc."""
    from atlas.inference.questions import load_question_set
    from atlas.sitedata.build import SiteDataError, load_short_labels
    from atlas.sitedata.inputs import find_cardset
    from atlas.story.core import FUNNEL_LABELS, PERIODS, QUARTERS, SCHEMA, TITLE
    from atlas.story.method import run_phases

    vocab = {
        TITLE,
        SCHEMA,
        "unknown",
        *PERIODS,
        *QUARTERS,
        *FUNNEL_LABELS.keys(),
        *FUNNEL_LABELS.values(),
    }
    meta = doc.get("meta") or {}
    tax = meta.get("taxonomy")
    if tax:
        vocab.add(tax)
        try:
            cs = find_cardset(tax)
        except (OSError, KeyError, ValueError, SiteDataError):
            cs = None
        if cs is not None:
            vocab |= set(cs.all_cards) | set(cs.groups) | set(cs.groups.values())
            vocab |= {c.statement for c in cs.all_cards.values()}
            labels = load_short_labels(f"{cs.name}.{cs.version}")
            vocab |= set(labels["groups"].values()) | set(labels["cards"].values())
    try:
        qs = load_question_set("facets", 2)
    except (OSError, KeyError, ValueError):
        qs = None
    if qs is not None:
        for q in qs.questions.values():
            crit = q.get("criteria")
            if isinstance(crit, dict):
                vocab |= set(crit.keys())
    tools_path = paths.CONFIGS / "tools.v1.yaml"
    if tools_path.exists():
        import yaml

        tools = (yaml.safe_load(tools_path.read_text()) or {}).get("tools") or []
        for t in tools:
            vocab.add(t["name"])
            vocab.add(t.get("category"))
            vocab |= set(t.get("aliases") or [])
    labels_path = paths.CONFIGS / "story_labels.toml"
    if labels_path.exists():
        import tomllib

        labels = tomllib.loads(labels_path.read_text(encoding="utf-8"))
        for table in ("domains", "roles"):
            vocab |= set((labels.get(table) or {}).values())
    for rid in (meta.get("runs") or {}).values():
        if rid:
            vocab.add(rid)
    method = doc.get("method") or {}
    for r in method.get("runs") or []:
        if r.get("run"):
            vocab.add(r["run"])
    for r in (method.get("wording") or {}).get("screen") or []:
        if r.get("run"):
            vocab.add(r["run"])
    rp = paths.CONFIGS / "run_phases.toml"
    vocab |= set(run_phases(rp)) | set(run_phases(rp).values())
    return vocab


def _ok_string(s: str, vocab: set) -> bool:
    return (
        s in vocab
        or bool(_IDENT.fullmatch(s))
        or bool(_STAMP.match(s))
        or bool(_SHA.fullmatch(s))
    )


def _walk(node, path: str, vocab: set, problems: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in BANNED_KEYS:
                problems.append(f"{path}.{k}: banned key {k!r}".lstrip("."))
                continue
            _walk(v, f"{path}.{k}".lstrip("."), vocab, problems)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", vocab, problems)
    elif isinstance(node, str):
        if path.startswith("terms.") and path.endswith(".term"):
            return  # term strings are governed by the S4 gate check below
        if not _ok_string(node, vocab):
            problems.append(f"{path}: unapproved string {node[:60]!r}")


def check_story(path) -> list[str]:
    """All problems found in ``story.json``; ``[]`` means publishable."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    problems: list[str] = []
    for gid, items in (doc.get("terms") or {}).items():
        for i, item in enumerate(items or []):
            nc = item.get("n_comments") or 0
            na = item.get("n_authors") or 0
            if nc < MIN_TERM_COMMENTS or na < MIN_TERM_AUTHORS:
                problems.append(
                    f"terms.{gid}[{i}]: term {item.get('term')!r} below gate "
                    f"(n_comments={nc}, n_authors={na})"
                )
    _walk(doc, "", _vocabulary(doc), problems)
    return problems

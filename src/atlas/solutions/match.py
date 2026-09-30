"""S5 matching: find tools.v1.yaml names in comment text.

Whole-word match on each tool's name and aliases. Terms longer than 3
characters match case-insensitively; terms of 3 or fewer match only
case-sensitively, so `Go` matches "Go" but not "go" and `AWS` never lives
inside "laws". A tool with `name_case: true` also matches its *name*
case-sensitively (aliases keep the usual rules), so `Wise` does not match
the word "wise". `find_mentions` returns the matched tool *names* (the only
tool words allowed in story.json). For bulk scans, `compile_tools` once and
pass the Matcher where a tools list is accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SHORT = 3  # terms of this length or shorter match case-sensitively only


@dataclass(frozen=True)
class Tool:
    name: str
    aliases: tuple = ()
    category: str = ""
    name_case: bool = False

    def terms(self) -> list[tuple[str, bool]]:
        """(term, force_case_sensitive) pairs: name plus aliases, in order,
        with duplicates removed. Only the name honors `name_case`."""
        seen, out = set(), []
        for t in (self.name, *self.aliases):
            if t and t not in seen:
                seen.add(t)
                out.append((t, self.name_case and t == self.name))
        return out


def load_tools(path) -> list[Tool]:
    """Read configs/tools.v1.yaml ({name, aliases, category, name_case} rows)."""
    data = yaml.safe_load(Path(path).read_bytes())
    return [
        Tool(
            name=row["name"],
            aliases=tuple(row.get("aliases") or ()),
            category=row.get("category") or "",
            name_case=bool(row.get("name_case")),
        )
        for row in data["tools"]
    ]


def _alternation(terms, flags) -> re.Pattern | None:
    """Whole-word alternation, longest term first so `llama.cpp` beats
    `llama` inside "llama.cpp" (a dot is not a word character)."""
    pats = [
        r"(?<!\w)" + re.escape(t) + r"(?!\w)"
        for t in sorted(terms, key=len, reverse=True)
    ]
    if not pats:
        return None
    return re.compile("|".join(pats), flags)


class Matcher:
    """Precompiled patterns for a tool list: one case-insensitive
    alternation for long terms, one case-sensitive for short terms."""

    def __init__(self, tools: list[Tool]):
        ci, cs = {}, {}
        for tool in tools:
            for term, force_cs in tool.terms():
                case_sensitive = len(term) <= SHORT or force_cs
                bucket = cs if case_sensitive else ci
                key = term if case_sensitive else term.lower()
                bucket.setdefault(key, set()).add(tool.name)
        self._ci_re = _alternation(ci, re.IGNORECASE)
        self._cs_re = _alternation(cs, 0)
        self._ci_names = ci
        self._cs_names = cs

    def find(self, text) -> set[str]:
        out = set()
        if not text:
            return out
        if self._ci_re is not None:
            for m in self._ci_re.finditer(text):
                out.update(self._ci_names.get(m.group(0).lower(), ()))
        if self._cs_re is not None:
            for m in self._cs_re.finditer(text):
                out.update(self._cs_names.get(m.group(0), ()))
        return out


def compile_tools(tools: list[Tool]) -> Matcher:
    return Matcher(tools)


def find_mentions(text: str, tools) -> set[str]:
    """Tool names mentioned in `text`; `tools` is a list[Tool] or a Matcher."""
    matcher = tools if isinstance(tools, Matcher) else Matcher(list(tools))
    return matcher.find(text)

"""Keyword baseline for firsthand-problem detection.

The pattern list is frozen at version 1 before any held-out evaluation;
changing it requires a new version.
"""

from __future__ import annotations

import re

PAIN_TERMS = (
    r"hate",
    r"annoying",
    r"frustrat\w*",
    r"broke",
    r"breaking",
    r"painful",
    r"struggl\w*",
    r"waste",
    r"wasted",
    r"spent\b.{0,40}?\b(?:hours|days)",
    r"keeps?\s+(?:failing|crashing|breaking)",
    r"can'?t|cannot|couldn'?t",
    r"nightmare",
    r"fighting",
    r"workaround",
)
PERSON = r"\b(?:i|we|my|our)\b"

PATTERNS = tuple(
    re.compile(
        rf"{PERSON}[^\n]{{0,60}}?\b(?:{term})|\b(?:{term})[^\n]{{0,60}}?{PERSON}",
        re.IGNORECASE,
    )
    for term in PAIN_TERMS
)


def keyword_score(text: str | None) -> float:
    """1.0 when a first-person marker sits within 60 chars of a pain term."""
    if not text:
        return 0.0
    return 1.0 if any(p.search(text) for p in PATTERNS) else 0.0

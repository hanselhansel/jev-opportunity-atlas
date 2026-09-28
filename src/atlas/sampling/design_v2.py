"""Design v2: free-signal strata for yield-aware stratified sampling.

Strata combine a pain-word flag, a comment-length bin, a half-year, and a
thread-type group, so the allocation can send more of the screen budget to
strata the pilot says are richer in firsthand problems.

PAIN_PATTERNS_VERSION is frozen: the pattern list below never changes after
the main draw. Any change needs a new version number and a new sample, because
strata drawn under different pattern versions are not comparable.
"""

from __future__ import annotations

import re

PAIN_PATTERNS_VERSION = 1

# First-person markers; "i.e." is stripped before matching so it never counts.
_MARKERS = re.compile(r"\b(?:i|we|my|our|us|me)\b", re.IGNORECASE)
_IE = re.compile(r"\bi\.e\.", re.IGNORECASE)

# Pain/behavior terms. Apostrophes accept ' or ’. Non-stem terms carry a
# trailing \b so, for example, "hacker" does not match "hack"; the stems
# frustrat/struggl match any suffix instead.
_TERMS = re.compile(
    r"\b(?:"
    r"spent|wasted|lost|broke|broken|breaking|keeps failing|"
    r"crash(?:es|ed|ing)?|outages?|frustrat\w*|painful|nightmare|"
    r"struggl\w*|hate[sd]?|annoying|workarounds?|hack(?:s|y|ed)?|"
    r"manual(?:ly)?|spreadsheets?|switched|migrated off|cancell?ed|"
    r"gave up|paying|pay for|too expensive|price hikes?|"
    r"can['’]t|cannot|couldn['’]t|no way to|stuck"
    r")\b",
    re.IGNORECASE,
)

_MAX_GAP = 80


def pain_flag(text: str | None) -> bool:
    """True when a first-person marker sits within 80 chars of a pain term."""
    if not text:
        return False
    cleaned = _IE.sub(" ", text)
    markers = list(_MARKERS.finditer(cleaned))
    if not markers:
        return False
    for term in _TERMS.finditer(cleaned):
        for marker in markers:
            if (
                max(marker.start(), term.start())
                - min(marker.end(), term.end())
                <= _MAX_GAP
            ):
                return True
    return False


def length_bin(word_count: int) -> str:
    """L0 < 15 words, L1 < 60, L2 < 200, else L3."""
    if word_count < 15:
        return "L0"
    if word_count < 60:
        return "L1"
    if word_count < 200:
        return "L2"
    return "L3"


def thread_group(thread_type: str | None) -> str:
    """ask_hn/tell_hn -> ask, show_hn/launch_hn -> show, story, else other."""
    if thread_type in ("ask_hn", "tell_hn"):
        return "ask"
    if thread_type in ("show_hn", "launch_hn"):
        return "show"
    if thread_type == "story":
        return "story"
    return "other"


def half_year(period: str) -> str:
    """P01..P06 -> H1, P07..P12 -> H2."""
    if not isinstance(period, str) or not re.fullmatch(r"P\d{2}", period):
        raise ValueError(f"bad period {period!r}")
    k = int(period[1:])
    if not 1 <= k <= 12:
        raise ValueError(f"bad period {period!r}")
    return "H1" if k <= 6 else "H2"


def design_stratum(pain: bool, lbin: str, period: str, tgroup: str) -> str:
    """Stratum label like "pain|L2|H1|ask" (at most 2*4*2*4 = 64 strata)."""
    return f"{'pain' if pain else 'nopain'}|{lbin}|{half_year(period)}|{tgroup}"

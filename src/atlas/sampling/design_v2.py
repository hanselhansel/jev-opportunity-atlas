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

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from atlas import contracts
from atlas.sampling import select, yield_alloc

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


def build_frame_v2(comments: pa.Table, stories: pa.Table) -> pa.Table:
    """Eligible comments labelled with v2 strata, sorted by comment_id.

    Comments carry id, story_id, period, thread_type, text_norm, word_count,
    eligible; stories carry id, thread_type. thread_type falls back to the
    root story's when the comment's is null, then to "unknown". `half` is the
    explore/confirm split from contracts.half_of(story_id), null when story_id
    is null. Null word_count counts as 0 words.
    """
    frame = comments.filter(pc.equal(comments.column("eligible"), True))
    idx = pc.index_in(frame.column("story_id"), value_set=stories.column("id"))
    story_tt = pc.take(stories.column("thread_type"), idx)
    ttype = pc.fill_null(
        pc.coalesce(frame.column("thread_type"), story_tt), "unknown"
    ).to_numpy(zero_copy_only=False)
    wc = (
        pc.fill_null(frame.column("word_count"), 0)
        .to_numpy(zero_copy_only=False)
        .astype(np.int32)
    )
    lbins = np.full(frame.num_rows, "L3", dtype="U2")
    lbins[wc < 200] = "L2"
    lbins[wc < 60] = "L1"
    lbins[wc < 15] = "L0"
    tg = np.array([thread_group(t) for t in ttype], dtype="U5")
    periods = frame.column("period").to_pylist()
    texts = frame.column("text_norm").to_pylist()
    story_ids = frame.column("story_id").to_pylist()
    halves = [
        contracts.half_of(sid) if sid is not None else None for sid in story_ids
    ]
    strata = [
        design_stratum(pain_flag(text), lbins[i], period, str(tg[i]))
        for i, (text, period) in enumerate(zip(texts, periods))
    ]
    order = np.argsort(
        frame.column("id").to_numpy(zero_copy_only=False), kind="stable"
    )
    take_idx = pa.array(order)
    return pa.table(
        {
            "comment_id": pa.array(
                frame.column("id").to_numpy(zero_copy_only=False)[order],
                type=pa.int64(),
            ),
            "story_id": pc.take(frame.column("story_id"), take_idx),
            "stratum": pa.array(np.asarray(strata, dtype=object)[order]),
            "half": pa.array(np.asarray(halves, dtype=object)[order]),
            "period": pc.take(frame.column("period"), take_idx),
            "word_count": pa.array(wc[order], type=pa.int32()),
        }
    )


def draw_allocated(
    frame: pa.Table, alloc: dict[str, int], seed: int, sample_id: str
) -> pa.Table:
    """Draw alloc[h] comments per v2 stratum; contract SAMPLE rows, batch 1.

    Every stratum present in `frame` must receive 1 <= alloc[h] <= N_h; extra
    alloc keys are allowed only with value 0.
    """
    sizes = select._sizes(frame)
    if any(a < 0 for a in alloc.values()):
        raise ValueError("negative allocation")
    if {h for h, a in alloc.items() if a > 0} != set(sizes):
        raise ValueError("positive alloc keys must equal the frame strata")
    for h, n_h in sizes.items():
        if alloc[h] > n_h:
            raise ValueError(f"alloc[{h}]={alloc[h]} exceeds stratum size {n_h}")
    rng = np.random.Generator(np.random.PCG64(seed))
    got = select._draw_rows(frame, alloc, rng)
    n = len(got["comment_id"])
    table = select._finish(
        frame,
        got["comment_id"],
        got["stratum"],
        sample_id,
        np.ones(n, dtype=np.int32),
        np.arange(n, dtype=np.int64),
    )
    select._check(table, frame.num_rows)
    return table


def write_design_manifest(
    table: pa.Table, meta: dict, design: dict, out_dir
) -> dict:
    """Write the sample parquet plus a JSON sidecar carrying the design block."""
    return select.write_manifest(table, {**meta, "design": design}, out_dir)


def design_block(
    *,
    floor_rate: float,
    min_n: int,
    budget_tokens: int,
    p: dict[str, float],
    c: dict[str, float],
    source: str,
    alloc: dict[str, int],
    N: dict[str, int],
    input_levels: dict | None = None,
) -> dict:
    """Everything downstream needs to reproduce or audit this draw."""
    return {
        "pain_patterns_version": PAIN_PATTERNS_VERSION,
        "floor_rate": floor_rate,
        "min_n": min_n,
        "budget_tokens": budget_tokens,
        "p_h": p,
        "c_h": c,
        "inputs_source": source,
        "input_levels": input_levels,
        "allocation": alloc,
        "expected_positives": yield_alloc.expected_positives(alloc, p),
        "expected_tokens": yield_alloc.expected_tokens(alloc, c),
        "largest_weight": yield_alloc.largest_weight(alloc, N),
    }

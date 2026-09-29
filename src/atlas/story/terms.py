"""S4: distinctive terms per group (aggregate words only).

Reads pain sentences locally and emits, per group, the words and two-word
phrases most overrepresented against all other placed problems
(Monroe, Colaresi and Quinn 2008 log-odds with an informative Dirichlet
prior scaled to 500). A term only leaves this module after the k-anonymity
gate: at least 20 distinct comments, 10 distinct authors, no long digit
run, no URL/email/handle shape, not denylisted, and never equal to a
frame author name.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter

from atlas import paths

K_COMMENTS = 20
K_AUTHORS = 10
TOP = 8
PRIOR_TOTAL = 500.0
MIN_LEN, MAX_LEN = 3, 30

_TOKEN = re.compile(r"[a-z][a-z0-9+#.-]*")
_DIGIT_RUN = re.compile(r"\d{4,}")
_EMAIL = re.compile(r"\S+@\S+")
_HANDLE = re.compile(r"(?:^|\s)@\w+")
_TLDS = (
    "com|org|net|edu|gov|mil|int|io|ai|dev|app|co|me|info|biz|name|pro|"
    "xyz|so|sh|tv|gg|fm|ly|to|is|it|at|be|br|ca|ch|cl|cn|cz|de|dk|ec|ee|"
    "es|eu|fi|fr|gr|hk|hr|hu|id|ie|il|in|jp|kr|lt|lu|lv|mx|my|nl|no|nz|"
    "ph|pk|pl|pt|ro|ru|sa|se|sg|si|sk|th|tn|tr|tw|ua|uk|us|uy|vn|za"
)
_URL = re.compile(
    rf"(?:https?|ftp|www)\.|^www$|^(?:https?|ftp)$|\b[\w-]+\.(?:{_TLDS})\b"
)


def _stopwords() -> frozenset:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    return frozenset(ENGLISH_STOP_WORDS)


def _load_denylist(path=None) -> frozenset:
    p = path or (paths.CONFIGS / "terms_denylist.txt")
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(
        ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#")
    )


def _tokens(text: str, stop: frozenset) -> list[str]:
    """Lowercased non-stopword tokens, 3 to 30 chars, ``[a-z]`` start."""
    return [
        t
        for t in _TOKEN.findall(text.lower())
        if MIN_LEN <= len(t) <= MAX_LEN and t not in stop
    ]


def _terms_in(text: str, stop: frozenset) -> Counter:
    """Unigram + bigram occurrence counts for one pain sentence."""
    toks = _tokens(text, stop)
    counts = Counter(toks)
    counts.update(f"{a} {b}" for a, b in itertools.pairwise(toks))
    return counts


def _lexical_ok(term: str, denylist: frozenset) -> bool:
    return not (
        _DIGIT_RUN.search(term)
        or _URL.search(term)
        or _EMAIL.search(term)
        or _HANDLE.search(term)
        or term in denylist
    )


def group_terms(
    frame,
    pain: dict,
    k_comments: int = K_COMMENTS,
    k_authors: int = K_AUTHORS,
    top: int = TOP,
    denylist=None,
) -> dict:
    """``{gid: [{term, z, lo95, hi95, n_comments, n_authors}]}``.

    ``frame`` supplies ``comment_id``, ``group``, ``author``, ``placed``;
    ``pain`` maps comment id to its pain sentence.
    """
    deny = _load_denylist() if denylist is None else frozenset(denylist)
    stop = _stopwords()
    authors = {str(a).lower() for a in frame["author"].dropna().unique()}

    gcount: dict[str, Counter] = {}
    gdocs: dict[str, Counter] = {}
    gauth: dict[str, dict[str, set]] = {}
    gtotal: Counter = Counter()
    placed = frame[frame["placed"]]
    for cid, gid, author in zip(
        placed["comment_id"], placed["group"], placed["author"]
    ):
        if not isinstance(gid, str):
            continue
        text = pain.get(int(cid))
        if not isinstance(text, str) or not text:
            continue
        counts = _terms_in(text, stop)
        if not counts:
            continue
        gcount.setdefault(gid, Counter()).update(counts)
        gdocs.setdefault(gid, Counter()).update(counts.keys())
        bag = gauth.setdefault(gid, {})
        known = isinstance(author, str) and author
        for term in counts:
            seen = bag.setdefault(term, set())
            if known:
                seen.add(author)
        gtotal[gid] += sum(counts.values())

    corpus = Counter()
    for c in gcount.values():
        corpus.update(c)
    corpus_total = sum(corpus.values())
    if not corpus_total:
        return {g: [] for g in gcount}

    candidates = []
    for gid, docs in gdocs.items():
        n = gtotal[gid]
        if not n:
            continue
        for term, ndocs in docs.items():
            if (
                ndocs < k_comments
                or len(gauth.get(gid, {}).get(term, ())) < k_authors
                or term in authors
                or not _lexical_ok(term, deny)
            ):
                continue
            cw = corpus[term]
            alpha = PRIOR_TOTAL * cw / corpus_total
            y_rest = cw - gcount[gid][term]
            n_rest = corpus_total - n
            den_g = n + PRIOR_TOTAL - gcount[gid][term] - alpha
            den_r = n_rest + PRIOR_TOTAL - y_rest - alpha
            if den_g <= 0 or den_r <= 0:
                continue
            delta = math.log((gcount[gid][term] + alpha) / den_g) - math.log(
                (y_rest + alpha) / den_r
            )
            var = 1.0 / (gcount[gid][term] + alpha) + 1.0 / (y_rest + alpha)
            z = delta / math.sqrt(var)
            p = math.erfc(abs(z) / math.sqrt(2.0))
            candidates.append((gid, term, z, delta, var, p))

    qvals = {}
    if candidates:
        import numpy as np

        from atlas.story.core import _bh_adjust

        adj = _bh_adjust(np.array([c[5] for c in candidates]))
        qvals = {i: q for i, q in enumerate(adj)}

    out: dict[str, list] = {g: [] for g in gcount}
    per_group: dict[str, list] = {g: [] for g in gcount}
    for i, (gid, term, z, delta, var, _p) in enumerate(candidates):
        if qvals.get(i, 1.0) >= 0.05 or z <= 0 or not math.isfinite(z):
            continue
        sigma = math.sqrt(var)
        per_group[gid].append(
            {
                "term": term,
                "z": float(z),
                "lo95": float(delta - 1.96 * sigma),
                "hi95": float(delta + 1.96 * sigma),
                "n_comments": int(gdocs[gid][term]),
                "n_authors": len(gauth[gid].get(term, ())),
            }
        )
    for gid, rows in per_group.items():
        rows.sort(key=lambda r: (-r["z"], r["term"]))
        out[gid] = rows[:top]
    return out


def story_section(args, story_path) -> None:
    """`story data --with terms`: load the frame + pain.parquet, merge
    the ``terms`` section into story.json."""
    import pyarrow.parquet as pq

    from atlas.story import frame as frame_mod
    from atlas.story import io
    from atlas.story.cli import _default_snapshot

    snapshot = args.snapshot or _default_snapshot()
    fr = frame_mod.load_frame(
        args.facet_sample,
        args.facets_run,
        args.assign_run,
        snapshot,
        cardset=args.cardset,
        version=args.version,
    )
    pain_path = paths.run_dir(args.assign_run) / "pain.parquet"
    pain = {
        int(r["comment_id"]): r["pain_sentence"]
        for r in pq.read_table(pain_path).to_pylist()
    }
    io.merge_section(story_path, "terms", group_terms(fr, pain))

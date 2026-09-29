"""S4 distinctive terms: the gate that keeps raw text out of story.json."""

import pandas as pd

from atlas.story import terms as terms_mod

COLS = ["comment_id", "group", "author", "placed", "phase"]
FILLER = "shared filler words here"


def _frame(rows):
    return pd.DataFrame(rows, columns=COLS)


def _docs(cid_start, gid, n, authors, make_pain):
    rows, pain = [], {}
    for i in range(n):
        cid = cid_start + i
        rows.append(
            {
                "comment_id": cid,
                "group": gid,
                "author": authors[i % len(authors)],
                "placed": True,
                "phase": "pos",
            }
        )
        pain[cid] = make_pain(i)
    return rows, pain


def _background():
    """200 placed rows of undistinctive filler split across two groups."""
    a_rows, a_pain = _docs(
        9_000_100_000,
        "g01",
        100,
        [f"wa{i:02d}" for i in range(25)],
        lambda i: FILLER,
    )
    b_rows, b_pain = _docs(
        9_000_200_000,
        "g02",
        100,
        [f"wb{i:02d}" for i in range(25)],
        lambda i: FILLER,
    )
    return a_rows + b_rows, a_pain | b_pain


def _emitted(result):
    return {t["term"] for terms in result.values() for t in terms}


def test_username_never_passes():
    """An author name written by 30 other authors in 40 comments is dropped."""
    rows, pain = _background()
    u_rows, u_pain = _docs(9_000_300_000, "g02", 2, ["syntheticuser"], lambda i: FILLER)
    rows += u_rows
    pain |= u_pain
    x_rows, x_pain = _docs(
        9_000_400_000,
        "g01",
        40,
        [f"xa{i:02d}" for i in range(30)],
        lambda i: "syntheticuser broke everything",
    )
    rows += x_rows
    pain |= x_pain
    result = terms_mod.group_terms(_frame(rows), pain)
    assert "syntheticuser" not in _emitted(result)


def test_url_and_email_dropped():
    rows, pain = _background()
    u_rows, u_pain = _docs(
        9_000_500_000,
        "g01",
        25,
        [f"ya{i:02d}" for i in range(12)],
        lambda i: "mail via example.com and internal.example.org daily",
    )
    rows += u_rows
    pain |= u_pain
    result = terms_mod.group_terms(_frame(rows), pain)
    emitted = _emitted(result)
    assert "example.com" not in emitted
    assert "internal.example.org" not in emitted
    assert not any("@" in t or "www" == t for t in emitted)


def test_rare_term_dropped():
    """19 comments fails the gate; 20 comments and 10 authors passes."""
    rows, pain = _background()
    r_rows, r_pain = _docs(
        9_000_600_000,
        "g01",
        19,
        [f"ra{i:02d}" for i in range(10)],
        lambda i: f"rareterm {FILLER}",
    )
    result = terms_mod.group_terms(_frame(rows + r_rows), pain | r_pain)
    assert "rareterm" not in _emitted(result)

    x_rows, x_pain = _docs(
        9_000_600_100,
        "g01",
        1,
        ["ra999"],
        lambda i: f"rareterm {FILLER}",
    )
    result = terms_mod.group_terms(
        _frame(rows + r_rows + x_rows), pain | r_pain | x_pain
    )
    g01_terms = {t["term"] for t in result["g01"]}
    assert "rareterm" in g01_terms

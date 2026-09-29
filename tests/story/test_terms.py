"""S4 distinctive terms: the gate that keeps raw text out of story.json."""

import json

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.story import terms as terms_mod
from tests.story import world

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


def test_planted_term_ranks_first():
    """A term injected only into g01 comments ranks first for g01."""
    rows, pain = _background()
    p_rows, p_pain = _docs(
        9_000_700_000,
        "g01",
        30,
        [f"pa{i:02d}" for i in range(15)],
        lambda i: f"{FILLER.split()[i % 4]} quixoticterm {FILLER}",
    )
    result = terms_mod.group_terms(_frame(rows + p_rows), pain | p_pain)
    assert result["g01"][0]["term"] == "quixoticterm"


def test_output_has_no_raw_sentence():
    """No emitted term is longer than a two-word phrase."""
    rows, pain = _background()
    p_rows, p_pain = _docs(
        9_000_800_000,
        "g01",
        30,
        [f"pa{i:02d}" for i in range(15)],
        lambda i: (
            "quixoticterm quixoticterm quixoticterm and the exact "
            "wording of a longer planted sentence survives"
        ),
    )
    result = terms_mod.group_terms(_frame(rows + p_rows), pain | p_pain)
    for terms in result.values():
        for item in terms:
            assert len(item["term"].split()) <= 2


DATA_ARGS = [
    "--snapshot",
    world.SNAPSHOT,
    "--facet-sample",
    world.SAMPLE,
    "--facets-run",
    world.FACETS_RUN,
    "--assign-run",
    world.ASSIGN_RUN,
    "--cardset",
    "syn",
    "--version",
    world.TV,
    "--audit-run",
    world.AUDIT_RUN,
    "--benchmark-run",
    world.BENCH_RUN,
    "--robust-screen",
    "runs/robust-screen-compare.json",
    "--robust-assign",
    "runs/robust-assign-compare.json",
    "--run-phases",
    "configs/run_phases.toml",
    "--R",
    "200",
    "--seed",
    "0",
]


def test_with_terms_writes_section(tmp_path, monkeypatch, capsys):
    """`story data --with terms` merges a gated terms section that passes
    `story check`."""
    world.build_world(tmp_path, monkeypatch)
    from atlas import paths
    from atlas.story import cli, frame

    fr = frame.load_frame(
        world.SAMPLE,
        world.FACETS_RUN,
        world.ASSIGN_RUN,
        world.SNAPSHOT,
        cardset="syn",
        version=world.TV,
    )
    pain_rows = [
        {
            "comment_id": int(r.comment_id),
            "pain_sentence": (
                f"alphaterm {FILLER}" if r.group == "g01" else f"betaterm {FILLER}"
            ),
        }
        for r in fr[fr["placed"]].itertuples()
    ]
    pq.write_table(
        pa.Table.from_pylist(pain_rows),
        paths.run_dir(world.ASSIGN_RUN) / "pain.parquet",
    )
    out = tmp_path / "story.json"
    cli.main(["story", "data", "--out", str(out), *DATA_ARGS, "--with", "terms"])
    doc = json.loads(out.read_text())
    assert doc["terms"]["g01"][0]["term"] == "alphaterm"
    assert doc["terms"]["g02"][0]["term"] == "betaterm"
    capsys.readouterr()
    cli.main(["story", "check", str(out)])
    assert "story: ok" in capsys.readouterr().out

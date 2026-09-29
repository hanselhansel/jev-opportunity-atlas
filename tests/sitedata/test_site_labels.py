"""L34: site pages show short labels where a reader needs them.

Source-level assertions in the style of test_pages.py: the page JavaScript
runs client-side, so these tests pin the wiring, not a rendered DOM.
"""

from __future__ import annotations

import re
from pathlib import Path

SITE_SRC = Path(__file__).resolve().parents[2] / "site" / "src"


def _index() -> str:
    return (SITE_SRC / "index.md").read_text()


def _finding_card() -> str:
    src = _index()
    m = re.search(r"function findingCard.*?\n\}\n", src, re.DOTALL)
    assert m, "findingCard not found"
    return m.group(0)


def test_finding_card_heading_is_the_short_label():
    body = _finding_card()
    h3 = re.search(r"<h3[^>]*>(.*?)</h3>", body, re.DOTALL)
    assert h3, "finding card has no heading"
    assert "f.short_label" in h3.group(1)


def test_finding_card_shows_the_full_statement_once():
    body = _finding_card()
    assert body.count("f.problem_statement") == 1
    assert "f.title" not in re.search(r"<h3[^>]*>(.*?)</h3>", body, re.DOTALL).group(1)


def test_share_tables_have_a_short_label_column():
    src = _index()
    cols = re.search(r"SHARE_COLS = \[(.*?)\]", src, re.DOTALL)
    assert cols, "SHARE_COLS not found"
    assert 'key: "short_label"' in cols.group(1)


def test_evidence_loads_a_card_label_map():
    src = (SITE_SRC / "evidence.md").read_text()
    assert "card_share.parquet" in src or "findings.parquet" in src
    assert "short_label" in src


def test_evidence_subtopic_cell_maps_to_label_and_titles_the_id():
    src = (SITE_SRC / "evidence.md").read_text()
    col = re.search(r'\{key: "subtopic"[^}]*\}', src)
    assert col, "subtopic column not found"
    assert "title:" in col.group(0) and "format:" in col.group(0)


def test_responsive_table_writes_title_attributes():
    src = (SITE_SRC / "components" / "table.js").read_text()
    assert 'setAttribute("title"' in src


def test_evidence_still_filters_by_card_id_through_the_hash():
    src = (SITE_SRC / "evidence.md").read_text()
    assert "r.subtopic === hashState.subtopic" in src
    assert "subtopic: r.subtopic" in src

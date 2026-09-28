import re
from pathlib import Path

PAGES = Path(__file__).resolve().parents[2] / "site" / "src"


def test_pages_set_and_banner():
    pages = sorted(PAGES.glob("*.md"))
    assert {p.name for p in pages} == {"index.md", "evidence.md", "method.md"}
    for p in pages:
        src = p.read_text()
        assert re.search(
            r'import\s*\{[^}]*\bbanner\b[^}]*\}\s*from\s*"\./components/badges\.js"',
            src,
        ), p.name
        assert "banner(meta)" in src, p.name


def test_no_page_maps_an_arrow_table():
    for p in PAGES.glob("*.md"):
        assert not re.search(r"\.parquet\(\)\)\.map\(", p.read_text()), p.name


def test_no_page_uses_duckdb():
    for name in ("index.md", "evidence.md"):
        assert "DuckDBClient" not in (PAGES / name).read_text()

"""HN comment HTML to plain text, and a conservative sentence splitter.

HN comment HTML uses <p> between paragraphs (no closing tag), <i>, <a>, <pre><code>,
and HTML entities. Link text on HN is the URL itself, so tags are dropped and text
kept. `drop_pre=True` discards <pre> code blocks, which is what language detection
wants as input.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

MAX_SENTENCES = 255  # Jev Choice accepts at most 255 options
_ABBREV = ("e.g.", "i.e.", "etc.", "vs.", "cf.")


class _Text(HTMLParser):
    def __init__(self, drop_pre: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.in_pre = False
        self.drop_pre = drop_pre

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.parts.append("\n\n")
        elif tag == "pre":
            self.in_pre = True
            if not self.drop_pre:
                self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False

    def handle_data(self, data):
        if self.drop_pre and self.in_pre:
            return
        self.parts.append(data)


def html_to_text(raw: str | None, drop_pre: bool = False) -> str:
    if not raw:
        return ""
    p = _Text(drop_pre=drop_pre)
    p.feed(raw)
    p.close()
    text = "".join(p.parts)  # convert_charrefs=True already unescaped entities once
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n").rstrip()


_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=\S)|\n{2,}")


def split_sentences(text: str) -> list[str]:
    pieces = [s.strip() for s in _BOUNDARY.split(text) if s and s.strip()]
    merged: list[str] = []
    for piece in pieces:
        if merged and merged[-1].lower().endswith(_ABBREV):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    if len(merged) > MAX_SENTENCES:
        merged = merged[: MAX_SENTENCES - 1] + [" ".join(merged[MAX_SENTENCES - 1 :])]
    return merged

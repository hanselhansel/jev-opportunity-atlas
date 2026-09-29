"""S6: runner items for the Show HN launch assign.

Each sampled story becomes one assign item: `comment_id` is the story id,
`pain_sentence` is the title with the "Show HN" prefix stripped, and
`sentences` is the title plus the first three sentences of `text_norm`,
capped at 300 characters total. Assignment reuses the two-level card engine
with launch-framed instructions and question sets `builders-g`/`builders-c`.
"""

from __future__ import annotations

import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from atlas import paths
from atlas.cards.engine.assign import assign
from atlas.sources.htmltext import split_sentences

GROUP_INSTRUCTIONS = (
    "Which group of needs does the product in `problem` address? "
    "`sentences` describes it."
)
CARD_INSTRUCTIONS = "Which need does the product in `problem` address?"
MAX_SENTENCE_CHARS = 300
MAX_TEXT_SENTENCES = 3
QUESTION_SET_PREFIX = "builders"

_PREFIX = re.compile(r"^\s*show\s*hn\b[\s:.\-–—]*", re.IGNORECASE)


def strip_prefix(title: str | None) -> str:
    """The launch title minus its "Show HN" marker."""
    t = (title or "").strip()
    return _PREFIX.sub("", t).strip() or t


def launch_sentences(
    title: str | None, text_norm: str | None, limit: int = MAX_SENTENCE_CHARS
) -> list[str]:
    """[title] plus up to 3 sentences of body, at most `limit` chars total."""
    parts = [title or ""] + split_sentences(text_norm or "")[
        :MAX_TEXT_SENTENCES
    ]
    out: list[str] = []
    used = 0
    for p in parts:
        if used + len(p) <= limit:
            out.append(p)
            used += len(p)
            continue
        room = limit - used
        if room > 0:
            out.append(p[:room])
        break
    return out


def launch_items(table, snapshot_id: str) -> list[dict]:
    """One assign item per sampled story id, in sample order."""
    ids = [int(i) for i in table.column("story_id").to_pylist()]
    sdir = paths.snapshot_dir(snapshot_id)
    stories = pq.read_table(
        sdir / "stories.parquet", columns=["id", "title", "text_norm"]
    )
    mask = pc.is_in(
        stories.column("id"), value_set=pa.array(ids, type=pa.int64())
    )
    got = {int(r["id"]): r for r in stories.filter(mask).to_pylist()}
    items = []
    for sid in ids:
        r = got.get(sid)
        if r is None:
            raise KeyError(f"story {sid} not in snapshot {snapshot_id}")
        title = r["title"] or ""
        items.append(
            {
                "comment_id": sid,
                "pain_sentence": strip_prefix(title),
                "sentences": launch_sentences(title, r["text_norm"]),
            }
        )
    return items


async def assign_launches(ctx, rows, cs):
    """`assign` with the launch instructions and the `builders` label prefix."""
    return await assign(
        ctx,
        rows,
        cs,
        question_set_prefix=QUESTION_SET_PREFIX,
        group_instructions=GROUP_INSTRUCTIONS,
        card_instructions=CARD_INSTRUCTIONS,
    )

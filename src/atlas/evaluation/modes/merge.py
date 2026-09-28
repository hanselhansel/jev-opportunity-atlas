"""Merge audit: how do two card statements relate? The queue hides the card
ids and Jev's expected score; the labeler sees only the statements."""

LABEL_SET = "merge_audit"

QUESTIONS = {"same": ("same", "related", "different")}
FREE_TEXT = {}
NEEDS_TEXT = False


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)

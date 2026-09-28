"""Deep-facet audit: the labeler answers the facet questions on a comment,
blind to Jev's facet answers. Comment text comes from the snapshot."""

LABEL_SET = "facet_audit"

YES_NO = ("yes", "no", "unsure")
QUESTIONS = {
    "workaround": YES_NO,
    "paid": YES_NO,
    "switched": YES_NO,
    "abandoned": YES_NO,
    "cost_time": YES_NO,
    "cost_money": YES_NO,
    "resolution": ("resolved", "unresolved", "unclear"),
}
FREE_TEXT = {}
NEEDS_TEXT = True


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)

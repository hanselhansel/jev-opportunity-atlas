"""Worth-interviewing review of top cards: a judgment, not a blind check.
The card's metrics are shown on purpose; the optional ``why`` note caps at
280 characters."""

LABEL_SET = "interview"

QUESTIONS = {"worth_interviewing": ("strong", "maybe", "no")}
FREE_TEXT = {"why": 280}
NEEDS_TEXT = False


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)

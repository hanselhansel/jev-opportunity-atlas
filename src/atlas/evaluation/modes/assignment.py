"""Card-assignment audit: does the shown card describe this pain sentence?
Half the shown cards are Jev's pick, half a random card in the same group;
which is which lives in the queue's hidden block and is never rendered."""

LABEL_SET = "assignment_audit"

QUESTIONS = {"fits": ("yes", "partly", "no", "unsure")}
FREE_TEXT = {}
NEEDS_TEXT = False


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)

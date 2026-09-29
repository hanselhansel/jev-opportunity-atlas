"""Card-fit audit: does the shown need card describe this pain sentence?
Half the shown cards are the model's pick, half a random card in the same
group; which is which lives in the queue data and is never rendered."""

LABEL_SET = "assignment_audit"

QUESTIONS = {"fits": ("yes", "partly", "no", "unsure")}
FREE_TEXT = {}
NEEDS_TEXT = False


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)


def render(item: dict) -> None:
    import streamlit as st

    st.markdown("#### Comment")
    st.markdown("> " + (item["pain_sentence"] or ""))
    st.markdown("#### Candidate need")
    st.markdown(item["card_statement"])
    st.caption("Does this need describe the problem in the comment?")

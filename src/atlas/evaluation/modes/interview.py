"""Worth-interviewing review of top cards: a judgment, not a blind check.
The card's metrics are shown on purpose; the optional ``why`` note caps at
280 characters."""

LABEL_SET = "interview"

QUESTIONS = {"worth_interviewing": ("strong", "maybe", "no")}
FREE_TEXT = {"why": 280}
NEEDS_TEXT = False


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)


def render(item: dict) -> None:
    import streamlit as st

    st.caption(
        "Judgment review, not a blind check. Metrics are shown on purpose."
    )
    st.markdown("#### Need")
    st.markdown(item["statement"])
    st.markdown(item["group_label"])
    m = item["metrics"]
    st.markdown(
        f"authors {m['authors']} · threads {m['threads']} "
        f"· periods {m['periods']} · domains {m['domains']}"
    )
    st.markdown("#### Comment examples")
    for example in item["examples"]:
        st.markdown("> " + example)

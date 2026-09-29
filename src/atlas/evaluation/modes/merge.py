"""Merge audit: how do two card statements relate? The queue keeps the card
ids and the model's expected score out of view; the labeler sees only the
statements."""

LABEL_SET = "merge_audit"

QUESTIONS = {"same": ("same", "related", "different")}
FREE_TEXT = {}
NEEDS_TEXT = False


def questions() -> dict[str, tuple[str, ...]]:
    return dict(QUESTIONS)


def render(item: dict) -> None:
    import streamlit as st

    st.markdown("#### Need A")
    st.markdown(item["card_a"])
    st.markdown("#### Need B")
    st.markdown(item["card_b"])
    st.caption("Are these the same underlying problem?")

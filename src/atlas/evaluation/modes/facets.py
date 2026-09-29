"""Deep-facet audit: the labeler judges the facet questions on a comment,
blind to the model's facet labels. Comment text comes from the snapshot."""

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


def render(item: dict) -> None:
    import streamlit as st

    st.subheader(item["story_title"])
    st.markdown(
        f"[view item](https://news.ycombinator.com/item?id={item['comment_id']})"
    )
    with st.expander("Parent"):
        st.markdown(item["parent"] or "")
    st.markdown("#### Comment")
    st.markdown(item["comment"] or "")

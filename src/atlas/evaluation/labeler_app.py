"""Blind labeling UI, launched by ``atlas label run`` via ``streamlit run``.

The app reads the label queue and snapshot comment text only. It never touches
model output: no band, score, rate, or repeat status is ever shown, so labels
cannot be anchored on Jev.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from atlas import paths
from atlas.evaluation import modes
from atlas.evaluation.queue import load_queue, sequence
from atlas.evaluation.store import (
    LabelStore,
    allowed_values,
    labels_path,
    repeats_path,
)

LABEL_SET = os.environ.get("ATLAS_LABEL_SET", "calibration")
_QUEUE_ENV = os.environ.get("ATLAS_QUEUE_PATH", "")
QUEUE_PATH = Path(_QUEUE_ENV) if _QUEUE_ENV else None
SNAPSHOT_ID = os.environ.get("ATLAS_SNAPSHOT_ID", "")
REVIEWER = os.environ.get("ATLAS_REVIEWER", "hansel")
PRIMARY_QUESTIONS = ("firsthand_problem", "account_type")


def _rubric() -> tuple[str, str]:
    path = paths.CONFIGS / "rubric.v1.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    version = "unknown"
    if text.startswith("---"):
        for line in text.split("---", 2)[1].splitlines():
            if line.strip().startswith("version:"):
                version = line.split(":", 1)[1].strip()
    return text, version


@st.cache_data
def _items(snapshot_id: str, ids: tuple[int, ...]) -> dict[int, dict]:
    from atlas.sources.items import load_items

    return {
        int(item["comment_id"]): item
        for item in load_items(paths.snapshot_dir(snapshot_id), list(ids))
    }


def _primary_done(cid: int, domain_ids: set[int], latest: dict) -> bool:
    questions = list(PRIMARY_QUESTIONS)
    if cid in domain_ids:
        questions.append("domain")
    return all((cid, q) in latest for q in questions)


def _first_unlabeled(seq, domain_ids, primary_latest, repeats_latest) -> int:
    for i, (cid, is_repeat) in enumerate(seq):
        if is_repeat:
            if (cid, "firsthand_problem") not in repeats_latest:
                return i
        elif not _primary_done(cid, domain_ids, primary_latest):
            return i
    return len(seq)


def _show_position(seq, pos, domain_ids, primary_latest, rubric_text,
                   rubric_version, label_set):
    cid, is_repeat = seq[pos]
    timing = st.session_state.timing
    if pos not in timing:
        timing[pos] = (datetime.now(UTC).isoformat(), time.monotonic())
    started_at, t0 = timing[pos]

    item = _items(SNAPSHOT_ID, tuple(c for c, _ in seq))[cid]
    st.subheader(item["story_title"])
    st.markdown(f"[view item](https://news.ycombinator.com/item?id={cid})")
    with st.expander("Parent"):
        st.markdown(item["parent"] or "")
    st.markdown("#### Comment")
    st.markdown(item["comment"] or "")

    options = allowed_values()
    shown = {q: options[q] for q in PRIMARY_QUESTIONS}
    if cid in domain_ids and not is_repeat:
        shown["domain"] = options["domain"]

    values = {}
    for question_id, opts in shown.items():
        key = f"{question_id}_{pos}"
        if not is_repeat:
            row = primary_latest.get((cid, question_id))
            if row is not None and key not in st.session_state:
                st.session_state[key] = row["value"]
        values[question_id] = st.radio(
            question_id.replace("_", " "), list(opts), index=None, key=key
        )

    with st.expander("Rubric"):
        st.markdown(rubric_text)

    all_set = all(v is not None for v in values.values())
    back_col, save_col = st.columns(2)
    if back_col.button("Back", disabled=pos == 0):
        st.session_state.pos = max(0, pos - 1)
        st.rerun()
    if save_col.button("Save and next", disabled=not all_set):
        ended_at = datetime.now(UTC).isoformat()
        seconds = time.monotonic() - t0
        store = LabelStore(repeats_path() if is_repeat else labels_path())
        for question_id, value in values.items():
            store.add(
                comment_id=cid,
                label_set=label_set,
                question_id=question_id,
                value=value,
                rubric_version=rubric_version,
                reviewer=REVIEWER,
                started_at=started_at,
                ended_at=ended_at,
                seconds=seconds,
            )
        st.session_state.pos = pos + 1
        st.rerun()


def _first_unlabeled_mode(seq, radio_qs, primary_latest, repeats_latest) -> int:
    for i, (cid, is_repeat) in enumerate(seq):
        latest = repeats_latest if is_repeat else primary_latest
        if not all((cid, q) in latest for q in radio_qs):
            return i
    return len(seq)


def _show_mode_position(queue, mode, seq, pos, primary_latest, rubric_text,
                        rubric_version, label_set):
    cid, is_repeat = seq[pos]
    timing = st.session_state.timing
    if pos not in timing:
        timing[pos] = (datetime.now(UTC).isoformat(), time.monotonic())
    started_at, t0 = timing[pos]

    view = dict(queue["items"][str(cid)])
    if mode.NEEDS_TEXT:
        ids = tuple(
            int(queue["items"][str(c)]["comment_id"]) for c, _ in seq
        )
        item = _items(SNAPSHOT_ID, ids)[view["comment_id"]]
        for key in ("story_title", "parent", "comment"):
            view[key] = item.get(key)
    mode.render(view)

    values = {}
    for qid, opts in mode.questions().items():
        key = f"{qid}_{pos}"
        if not is_repeat:
            row = primary_latest.get((cid, qid))
            if row is not None and key not in st.session_state:
                st.session_state[key] = row["value"]
        values[qid] = st.radio(
            qid.replace("_", " "), list(opts), index=None, key=key
        )
    if not is_repeat:
        for qid, limit in mode.FREE_TEXT.items():
            key = f"{qid}_{pos}"
            row = primary_latest.get((cid, qid))
            if row is not None and key not in st.session_state:
                st.session_state[key] = row["value"]
            values[qid] = st.text_input(
                f"{qid} (optional, at most {limit} characters)",
                max_chars=limit,
                key=key,
            )

    with st.expander("Rubric"):
        st.markdown(rubric_text)

    all_set = all(values[q] is not None for q in mode.questions())
    back_col, save_col = st.columns(2)
    if back_col.button("Back", disabled=pos == 0):
        st.session_state.pos = max(0, pos - 1)
        st.rerun()
    if save_col.button("Save and next", disabled=not all_set):
        ended_at = datetime.now(UTC).isoformat()
        seconds = time.monotonic() - t0
        store = LabelStore(repeats_path() if is_repeat else labels_path())
        for qid, value in values.items():
            if qid in mode.FREE_TEXT:
                value = (value or "").strip()
                if not value:
                    continue
            store.add(
                comment_id=cid,
                label_set=label_set,
                question_id=qid,
                value=value,
                rubric_version=rubric_version,
                reviewer=REVIEWER,
                started_at=started_at,
                ended_at=ended_at,
                seconds=seconds,
            )
        st.session_state.pos = pos + 1
        st.rerun()


def main() -> None:
    if QUEUE_PATH is None or not QUEUE_PATH.is_file():
        st.error("label queue not found; launch via `atlas label run`")
        return
    queue = load_queue(QUEUE_PATH)
    seq = sequence(queue)
    mode = modes.get(queue.get("label_set"))
    label_set = queue.get("label_set") or LABEL_SET
    domain_ids = set(queue.get("domain_ids", []))
    primary_latest = LabelStore(labels_path()).latest(label_set)
    repeats_latest = LabelStore(repeats_path()).latest(label_set)
    rubric_text, rubric_version = _rubric()

    if "pos" not in st.session_state:
        if mode is None:
            st.session_state.pos = _first_unlabeled(
                seq, domain_ids, primary_latest, repeats_latest
            )
        else:
            st.session_state.pos = _first_unlabeled_mode(
                seq, list(mode.questions()), primary_latest, repeats_latest
            )
    st.session_state.setdefault("timing", {})

    pos = st.session_state.pos
    st.progress(pos / len(seq) if seq else 1.0, text=f"{pos} / {len(seq)}")
    if pos >= len(seq):
        st.success("All items in this queue are labeled.")
        return
    if mode is None:
        _show_position(
            seq, pos, domain_ids, primary_latest, rubric_text,
            rubric_version, label_set
        )
    else:
        _show_mode_position(
            queue, mode, seq, pos, primary_latest, rubric_text,
            rubric_version, label_set
        )


main()

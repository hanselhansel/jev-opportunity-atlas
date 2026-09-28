"""Frozen data contracts shared by all subsystems. Change only by a reviewed PR that
bumps SCHEMA_VERSION and updates every reader."""

from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = 1
UTC_TS = pa.timestamp("s", tz="UTC")
N_PERIODS = 12

THREAD_TYPES = (
    "ask_hn",
    "show_hn",
    "launch_hn",
    "tell_hn",
    "story",
    "poll",
    "job",
    "unknown",
)
EXCLUSION_REASONS = (
    "out_of_window",
    "deleted",
    "dead",
    "empty_text",
    "non_english",
    "not_comment",
)


def period_of(ts: int, window_start: int, window_end: int) -> str | None:
    """Window-relative period "P01".."P12"; each is 1/12 of the half-open window."""
    if not window_start <= ts < window_end:
        return None
    k = (ts - window_start) * N_PERIODS // (window_end - window_start)
    return f"P{k + 1:02d}"


# One row per comment item fetched in the scan range (in-window or not).
# The original HTML stays in the raw shards; it is not duplicated here.
COMMENTS = pa.schema(
    [
        ("id", pa.int64()),
        ("time", pa.int64()),
        ("created_at", UTC_TS),
        ("month", pa.string()),  # calendar "2025-10", display only
        ("period", pa.string()),  # "P01".."P12" (period_of), null when out of window
        ("parent_id", pa.int64()),
        (
            "story_id",
            pa.int64(),
        ),  # root story, resolved through ancestors; null if unresolved
        ("depth", pa.int16()),  # 1 = direct reply to the story
        ("text_norm", pa.string()),
        ("sentences", pa.list_(pa.string())),  # sentence i has id f"s{i}", at most 255
        ("text_sha256", pa.string()),  # sha256 of text_norm, utf-8
        ("author", pa.string()),  # local only; never exported
        ("thread_type", pa.string()),  # one of THREAD_TYPES
        ("state", pa.string()),  # ok | dead | deleted
        ("in_window", pa.bool_()),
        ("lang", pa.string()),  # ISO 639-1, or "und"
        ("word_count", pa.int32()),
        ("eligible", pa.bool_()),
        (
            "exclusion_reason",
            pa.string(),
        ),  # null when eligible, else one of EXCLUSION_REASONS
    ]
)

# One row per story, job, or poll item, including out-of-range roots fetched as context.
STORIES = pa.schema(
    [
        ("id", pa.int64()),
        ("time", pa.int64()),
        ("created_at", UTC_TS),
        ("type", pa.string()),
        ("title", pa.string()),
        ("url", pa.string()),
        ("text_norm", pa.string()),
        ("score", pa.int32()),
        ("descendants", pa.int32()),  # as of fetch time
        ("thread_type", pa.string()),
        ("state", pa.string()),
        ("in_window", pa.bool_()),
        ("fetched_at", pa.string()),
    ]
)

# Ancestor comments outside the scan range, fetched only for parent context.
CONTEXT = pa.schema(
    [
        ("id", pa.int64()),
        ("time", pa.int64()),
        ("type", pa.string()),
        ("parent_id", pa.int64()),
        ("text_norm", pa.string()),
        ("state", pa.string()),
        ("fetched_at", pa.string()),
    ]
)

# Coverage counts; dimensions include state, type, exclusion_reason, period, thread_type.
COVERAGE = pa.schema(
    [
        ("dimension", pa.string()),
        ("key", pa.string()),
        ("count", pa.int64()),
    ]
)

# One row per selected unit in a probability sample.
SAMPLE = pa.schema(
    [
        ("sample_id", pa.string()),
        ("comment_id", pa.int64()),
        ("story_id", pa.int64()),
        ("stratum", pa.string()),
        ("inclusion_prob", pa.float64()),
        ("weight", pa.float64()),
        ("batch", pa.int32()),  # 1 = first draw, 2+ = recorded expansions
        ("draw_order", pa.int64()),
    ]
)

# Long format: one row per (comment, question) answer.
ANSWERS = pa.schema(
    [
        ("run_id", pa.string()),
        ("comment_id", pa.int64()),
        ("question_set", pa.string()),  # e.g. "screen@0"
        ("question_id", pa.string()),
        ("qtype", pa.string()),  # noul | choice | score
        ("noul", pa.float64()),
        ("choice", pa.string()),
        ("score", pa.float64()),
        ("probabilities_json", pa.string()),
        ("confidence", pa.float64()),  # TypeSafe-defined; null for noul
        ("model_returned", pa.string()),
        ("request_id", pa.string()),
        ("logical_call_id", pa.string()),
        ("cache_hit", pa.bool_()),
    ]
)

# Human labels, append-only.
LABELS = pa.schema(
    [
        ("label_id", pa.string()),
        ("comment_id", pa.int64()),
        ("label_set", pa.string()),  # calibration | heldout | edge | spike
        ("question_id", pa.string()),
        ("value", pa.string()),  # "yes" | "no" | "unsure" | choice option
        ("rubric_version", pa.string()),
        ("reviewer", pa.string()),
        ("started_at", pa.string()),
        ("ended_at", pa.string()),
        ("seconds", pa.float64()),
    ]
)

# Attempt ledger rows are JSON lines with exactly these keys, in this order.
LEDGER_FIELDS = (
    "run_id",
    "logical_call_id",
    "attempt",
    "comment_id",
    "question_set",
    "question_count",
    "input_hash",
    "model_requested",
    "model_returned",
    "request_id",
    "started_at",
    "ended_at",
    "queue_ms",
    "request_ms",
    "backoff_ms",
    "http_status",
    "error_type",
    "validation",
    "input_tokens",
    "output_tokens",
    "cache",
    "price_version",
    "cost_usd",
    "cost_class",
)
COST_CLASSES = ("calculated", "unknown", "replay", "pending", "none")

# ---- Analysis layer (plan 2). Additive; existing schemas are unchanged. ----

SPLIT_SALT = "jev-atlas-2026-09-29"


def half_of(story_id: int) -> str:
    """Explore/confirm split by thread, fixed before any analysis. Deterministic."""
    import hashlib

    digest = hashlib.sha256(f"{SPLIT_SALT}:{story_id}".encode()).digest()
    return "explore" if digest[0] % 2 == 0 else "confirm"


# Need cards: solution-independent problem statements, versioned. Text is written by
# Claude and approved by Hansel; Jev never writes these.
CARDS = pa.schema([
    ("card_id", pa.string()),          # stable, e.g. "c0042"
    ("group_id", pa.string()),         # level-1 group, e.g. "g07"
    ("group_label", pa.string()),
    ("statement", pa.string()),        # one sentence, solution-independent
    ("taxonomy_version", pa.string()), # e.g. "t1"
    ("status", pa.string()),           # draft | approved | merged_into:<card_id> | retired
    ("author", pa.string()),           # "claude+hansel" or "hansel"
    ("created_at", pa.string()),
])

# One row per (comment, taxonomy version): where Jev placed the comment.
ASSIGNMENTS = pa.schema([
    ("run_id", pa.string()),
    ("comment_id", pa.int64()),
    ("taxonomy_version", pa.string()),
    ("group_id", pa.string()),         # "none" when Jev picked none of the groups
    ("group_p", pa.float64()),
    ("group_confidence", pa.float64()),
    ("card_id", pa.string()),          # "none" when no card fits; null when group is none
    ("card_p", pa.float64()),
    ("card_confidence", pa.float64()),
    ("verified_p", pa.float64()),      # membership noul, null until verified
])

# Every human-labeled item and how it was drawn. PPI needs known selection
# probabilities; hand-picked items are never used for estimates.
GOLD_DRAWS = pa.schema([
    ("label_set", pa.string()),
    ("comment_id", pa.int64()),
    ("draw_stratum", pa.string()),
    ("selection_prob", pa.float64()),  # probability this item entered the gold set
    ("seed", pa.int64()),
    ("purpose", pa.string()),          # estimate | calibration | audit
])

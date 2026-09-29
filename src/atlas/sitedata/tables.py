"""Site table contract: DRAFT until the first finding.

Every table the Observable Framework site reads, as Parquet. Nothing here carries
comment text or usernames; the evidence table keeps only ids, scores, and a hash.
"""

from __future__ import annotations

import pyarrow as pa

from atlas.contracts import COVERAGE
from atlas.sitedata.fixtures import write_fixtures  # noqa: F401  (re-export)

BADGES = ("measured", "calculated", "estimated", "unknown")
LANES = ("breadth", "discovery")

SITE_TABLES: dict[str, pa.Schema] = {
    "meta": pa.schema(
        [
            ("key", pa.string()),
            ("value", pa.string()),
        ]
    ),
    "coverage": COVERAGE,
    "domain_share": pa.schema(
        [
            ("lane", pa.string()),
            ("domain", pa.string()),
            ("period", pa.string()),
            ("n", pa.int64()),
            ("weighted_share", pa.float64()),
            ("ci_low", pa.float64()),
            ("ci_high", pa.float64()),
            ("too_few", pa.bool_()),
            ("badge", pa.string()),
            ("run_id", pa.string()),
            ("question_set", pa.string()),
            ("denominator", pa.string()),
        ]
    ),
    "card_share": pa.schema(
        [
            ("level", pa.string()),
            ("id", pa.string()),
            ("label", pa.string()),
            ("population", pa.string()),
            ("bucket", pa.string()),
            ("share", pa.float64()),
            ("lo", pa.float64()),
            ("hi", pa.float64()),
            ("n_items", pa.int64()),
            ("n_authors", pa.int64()),
            ("p_adj", pa.float64()),
            ("qualifier", pa.string()),
        ]
    ),
    "robustness": pa.schema(
        [
            ("check", pa.string()),
            ("run_id", pa.string()),
            ("metric", pa.string()),
            ("value", pa.float64()),
            ("lo", pa.float64()),
            ("hi", pa.float64()),
            ("n", pa.int64()),
        ]
    ),
    "evidence": pa.schema(
        [
            ("comment_id", pa.int64()),
            ("lane", pa.string()),
            ("domain", pa.string()),
            ("subtopic", pa.string()),
            ("period", pa.string()),
            ("story_id", pa.int64()),
            ("thread_type", pa.string()),
            ("firsthand_p", pa.float64()),
            ("account_type", pa.string()),
            ("specificity", pa.float64()),
            ("workaround_p", pa.float64()),
            ("consequence_any_p", pa.float64()),
            ("evidence_strength", pa.float64()),
            ("support_sentence_id", pa.string()),
            ("model_returned", pa.string()),
            ("run_id", pa.string()),
            ("human_label", pa.string()),
            ("text_sha256", pa.string()),
            ("question_set", pa.string()),
            ("taxonomy_version", pa.string()),
            ("weight", pa.float64()),
            ("confidence", pa.float64()),
            ("probabilities_json", pa.string()),
        ]
    ),
    "findings": pa.schema(
        [
            ("finding_id", pa.string()),
            ("title", pa.string()),
            ("domain", pa.string()),
            ("subtopic", pa.string()),
            ("n_comments", pa.int64()),
            ("n_threads", pa.int64()),
            ("n_authors", pa.int64()),
            ("months_present", pa.int64()),
            ("contradicting", pa.bool_()),
            ("status", pa.string()),
            ("lane", pa.string()),
            ("problem_statement", pa.string()),
            ("user_workflow", pa.string()),
            ("workarounds_json", pa.string()),
            ("solutions_named_json", pa.string()),
            ("contradicting_n", pa.int64()),
            ("unknowns_json", pa.string()),
            ("discovery_question", pa.string()),
            ("first_period", pa.string()),
            ("last_period", pa.string()),
            ("max_thread_share", pa.float64()),
            ("run_id", pa.string()),
            ("question_set", pa.string()),
            ("taxonomy_version", pa.string()),
            ("validated_at", pa.string()),
        ]
    ),
    "finding_evidence": pa.schema(
        [
            ("finding_id", pa.string()),
            ("comment_id", pa.int64()),
            ("match_p", pa.float64()),
            ("role", pa.string()),  # supporting | contradicting
        ]
    ),
    "runs": pa.schema(
        [
            ("run_id", pa.string()),
            ("phase", pa.string()),
            ("calls", pa.int64()),
            ("attempts", pa.int64()),
            ("retries", pa.int64()),
            ("unknown_attempts", pa.int64()),
            ("calculated_usd", pa.float64()),
            ("wall_s", pa.float64()),
            ("p50_ms", pa.float64()),
            ("p95_ms", pa.float64()),
            ("cache_hits", pa.int64()),
            ("kind", pa.string()),
        ]
    ),
    "quality": pa.schema(
        [
            ("question_id", pa.string()),
            ("label_set", pa.string()),
            ("metric", pa.string()),
            ("value", pa.float64()),
            ("ci_low", pa.float64()),
            ("ci_high", pa.float64()),
            ("n", pa.int64()),
        ]
    ),
}

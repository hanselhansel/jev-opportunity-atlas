"""``robustness`` rows: how the headline numbers move under reworded questions.

Inputs are the parsed JSON outputs of ``robust compare-screen`` and
``robust compare-assign`` (``atlas.robustness.compare``). Screen wording
contributes one ``prevalence`` row per run (with its interval) plus
``agreement``, ``kappa``, and ``spearman`` per paraphrase run; assign wording
contributes ``group_agreement``, ``card_agreement``, and
``max_abs_share_diff`` per paraphrase run. When neither JSON is given the
table is empty.
"""

from __future__ import annotations

SCREEN_METRICS = ("agreement", "kappa", "spearman")
ASSIGN_METRICS = (
    ("group_agreement", "group_agreement", "n_common"),
    ("card_agreement", "card_agreement", "n_common"),
    ("max_abs_share_diff", "max_abs_diff", "n"),
)


def _row(check, run_id, metric, value, lo, hi, n) -> dict:
    return {
        "check": check,
        "run_id": run_id,
        "metric": metric,
        "value": value,
        "lo": lo,
        "hi": hi,
        "n": n,
    }


def robustness_rows(screen: dict | None = None, assign: dict | None = None) -> list[dict]:
    """Site ``robustness`` rows from the two compare JSON documents."""
    rows = []
    for run_id, entry in sorted((screen or {}).get("runs", {}).items()):
        rows.append(
            _row(
                "screen_wording",
                run_id,
                "prevalence",
                entry.get("prevalence"),
                entry.get("ci_low"),
                entry.get("ci_high"),
                entry.get("n"),
            )
        )
        vs = entry.get("vs_main") or {}
        for metric in SCREEN_METRICS:
            if metric in vs:
                rows.append(
                    _row(
                        "screen_wording",
                        run_id,
                        metric,
                        vs.get(metric),
                        None,
                        None,
                        vs.get("n"),
                    )
                )
    for run_id, entry in sorted((assign or {}).get("runs", {}).items()):
        for metric, key, n_key in ASSIGN_METRICS:
            rows.append(
                _row(
                    "assign_wording",
                    run_id,
                    metric,
                    entry.get(key),
                    None,
                    None,
                    entry.get(n_key),
                )
            )
    return rows

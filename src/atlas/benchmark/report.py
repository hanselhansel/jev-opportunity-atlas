"""Markdown rendering for the synthetic benchmark score dict."""

from __future__ import annotations

from atlas.benchmark.score import DISCLAIMER


def _num(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def render_markdown(s: dict) -> str:
    """The benchmark report body; the first line is always the synthetic
    disclaimer heading."""
    lines = [
        f"# {DISCLAIMER}",
        "",
        f"- run_id: `{s['run_id']}`",
        f"- cases_version: `{s['cases_version']}`",
        f"- n_cases: {s['n_cases']}",
        "",
        "## firsthand_problem",
        "",
        "| mode | threshold | accuracy | precision | recall | n_missing |",
        "|---|---|---|---|---|---|",
    ]
    for mode, by_t in s["firsthand"].items():
        for t, m in by_t.items():
            lines.append(
                f"| {mode} | {t} | {_num(m['accuracy'])} "
                f"| {_num(m['precision'])} | {_num(m['recall'])} "
                f"| {m['n_missing']} |"
            )
    lines += [
        "",
        "## firsthand_problem by category (threshold 0.5)",
        "",
        "| category | mode | n | correct | accuracy |",
        "|---|---|---|---|---|",
    ]
    for mode, by_cat in s["by_category"].items():
        for cat, e in by_cat.items():
            lines.append(
                f"| {cat} | {mode} | {e['n']} | {e['correct']} "
                f"| {_num(e['accuracy'])} |"
            )
    at = s["account_type"]
    lines += [
        "",
        "## account_type",
        "",
        "| n | correct | missing | accuracy |",
        "|---|---|---|---|",
        (
            f"| {at['n']} | {at['correct']} | {at['missing']} "
            f"| {_num(at['accuracy'])} |"
        ),
        "",
        "## facets (facets@2)",
        "",
        "| facet | n | correct | missing | accuracy |",
        "|---|---|---|---|---|",
    ]
    for facet, e in s["facets"].items():
        lines.append(
            f"| {facet} | {e['n']} | {e['correct']} | {e['missing']} "
            f"| {_num(e['accuracy'])} |"
        )
    cards = s["cards"]
    carded = cards["carded"]
    none = cards["none"]
    lines += [
        "",
        "## cards (pilot.t1)",
        "",
        (
            f"- top-1 accuracy: {_num(cards['top1_accuracy'])} "
            f"({cards['correct']}/{cards['n']})"
        ),
        f"- expected none: {none['correct']}/{none['n']} correctly none",
        (
            f"- expected a card: {carded['correct']}/{carded['n']} correct, "
            f"{carded['false_none']} falsely none, "
            f"{carded['group_correct']} in the right group"
        ),
        "",
        "## misses",
        "",
        "| case_id | category | question | expected | got | p |",
        "|---|---|---|---|---|---|",
    ]
    for m in s["misses"]:
        got = "missing" if m["got"] is None else str(m["got"])
        p = "n/a" if m["p"] is None else f"{m['p']:.3f}"
        lines.append(
            f"| {m['case_id']} | {m['category']} | {m['question']} "
            f"| {m['expected']} | {got} | {p} |"
        )
    return "\n".join(lines) + "\n"

"""Transparent need-card ranking and the explore/confirm finding gate.

Ranking weights live in ``configs/ranking.toml`` so anyone can change them.
Scores are relative within the input set: a discovery ranking over sampled,
assigned comments, not population prevalence. Population claims use
``atlas.estimation`` (L12).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from atlas import contracts, paths


def load_weights(path=None) -> dict[str, float]:
    """Read ``[weights]`` from ``path`` or ``paths.CONFIGS / 'ranking.toml'``."""
    p = Path(path) if path is not None else paths.CONFIGS / "ranking.toml"
    with p.open("rb") as f:
        return dict(tomllib.load(f)["weights"])


def ranking_inputs(metrics, convergence=None) -> pa.Table:
    """``metrics`` plus the derived columns the default weights consume.

    Adds ``n_authors_capped`` (alias of ``n_comments_capped``: the comment count
    with each author capped at ``author_cap``), ``commercial_rate`` (row max of
    paid/switched/abandoned rates, ignoring nulls) when absent, and
    ``effective_domains``/``effective_roles`` left-joined from ``convergence``
    on ``card_id`` when given.
    """
    import duckdb

    con = duckdb.connect()
    try:
        con.register("metrics", metrics)
        derived = ["m.n_comments_capped as n_authors_capped"]
        if "commercial_rate" not in metrics.column_names:
            derived.append(
                "greatest(m.paid_rate, m.switched_rate, m.abandoned_rate) "
                "as commercial_rate"
            )
        conv_cols = ""
        join = ""
        if convergence is not None:
            con.register("conv", convergence)
            conv_cols = ", c.effective_domains, c.effective_roles"
            join = "left join conv c on c.card_id = m.card_id"
        return con.execute(
            f"select m.*, {', '.join(derived)}{conv_cols} "
            f"from metrics m {join} order by m.card_id"
        ).to_arrow_table()
    finally:
        con.close()


def rank_cards(metrics, weights) -> pa.Table:
    """Rank cards by the weighted sum of min-max normalized components.

    Every key in ``weights`` (zero weights included) must name a column in
    ``metrics``, else ValueError. Each component is normalized across cards to
    [0, 1] as ``(x - min) / (max - min)``; when ``max == min`` or the column is
    all null, every value maps to 0.0, and nulls always map to 0.0. The score
    is ``sum(weights[k] * norm_k)``; negative weights are allowed. Rank is a
    1..n ordinal, highest score first, ties broken by ``card_id`` ascending.
    Scores are relative within the input set: a discovery ranking, not
    prevalence.
    """
    names = set(metrics.column_names)
    for key in weights:
        if key not in names:
            raise ValueError(
                f"ranking weight {key!r} has no matching column in metrics"
            )
    card_ids = metrics["card_id"].to_pylist()
    n = len(card_ids)
    norms = {}
    for key in weights:
        vals = metrics[key].to_pylist()
        present = [v for v in vals if v is not None]
        if not present or max(present) == min(present):
            norms[key] = [0.0] * n
        else:
            lo, hi = min(present), max(present)
            norms[key] = [
                0.0 if v is None else (v - lo) / (hi - lo) for v in vals
            ]
    scores = [
        sum(weights[k] * norms[k][i] for k in weights) for i in range(n)
    ]
    order = sorted(range(n), key=lambda i: (-scores[i], card_ids[i]))
    weights_json = json.dumps(weights, sort_keys=True)

    out = {"card_id": [], "score": [], "rank": [], "weights_json": []}
    for key in weights:
        out[f"{key}_norm"] = []
    for rank, i in enumerate(order, start=1):
        out["card_id"].append(card_ids[i])
        for key in weights:
            out[f"{key}_norm"].append(norms[key][i])
        out["score"].append(scores[i])
        out["rank"].append(rank)
        out["weights_json"].append(weights_json)

    card_type = metrics.schema.field("card_id").type
    schema = pa.schema(
        [("card_id", card_type)]
        + [(f"{k}_norm", pa.float64()) for k in weights]
        + [
            ("score", pa.float64()),
            ("rank", pa.int64()),
            ("weights_json", pa.string()),
        ]
    )
    return pa.Table.from_pydict(out, schema=schema)


def split_by_half(table, story_col="story_id") -> dict[str, pa.Table]:
    """Split rows into {"explore", "confirm"} via ``contracts.half_of``.

    Rows with a null ``story_col`` are dropped.
    """
    stories = table[story_col].to_pylist()
    halves = pa.array(
        [None if s is None else contracts.half_of(int(s)) for s in stories],
        type=pa.string(),
    )
    return {
        "explore": table.filter(pc.equal(halves, "explore")),
        "confirm": table.filter(pc.equal(halves, "confirm")),
    }


def load_criteria(path=None) -> dict:
    """Read ``[criteria]`` from ``path`` or ``paths.CONFIGS /
    'finding_criteria.toml'``."""
    p = (
        Path(path)
        if path is not None
        else paths.CONFIGS / "finding_criteria.toml"
    )
    with p.open("rb") as f:
        return dict(tomllib.load(f)["criteria"])


_CRITERIA_CHECKS = (
    ("n_authors", "min_authors", ">="),
    ("n_periods", "min_periods", ">="),
    ("n_domains", "min_domains", ">="),
    ("max_thread_share", "max_thread_share", "<="),
)


def _half_reasons(row, half, criteria):
    """Failure reasons for one card in one half; empty list when it passes."""
    if row is None:
        return [f"{half}: missing"]
    reasons = []
    for col, key, op in _CRITERIA_CHECKS:
        val = row.get(col)
        limit = criteria[key]
        if val is None:
            reasons.append(f"{half}: {col} is null")
        elif op == ">=" and val < limit:
            reasons.append(f"{half}: {col} {val} < {limit}")
        elif op == "<=" and val > limit:
            reasons.append(f"{half}: {col} {val} > {limit}")
    return reasons


def evaluate_criteria(metrics_explore, metrics_confirm, criteria) -> pa.Table:
    """Pre-registered finding gate over the explore and confirm halves.

    A card is a candidate only when it meets every criterion in both halves.
    ``criteria`` keys: min_authors, min_periods, min_domains (lower bounds on
    n_authors, n_periods, n_domains) and max_thread_share (upper bound). A null
    metric value fails; a card absent from a half fails with reason
    ``"<half>: missing"``. Output is sorted by card_id with columns card_id,
    passes_explore, passes_confirm, candidate, reasons (list<string>).
    """
    explore = {r["card_id"]: r for r in metrics_explore.to_pylist()}
    confirm = {r["card_id"]: r for r in metrics_confirm.to_pylist()}
    schema = pa.schema(
        [
            ("card_id", pa.string()),
            ("passes_explore", pa.bool_()),
            ("passes_confirm", pa.bool_()),
            ("candidate", pa.bool_()),
            ("reasons", pa.list_(pa.string())),
        ]
    )
    rows = []
    for card_id in sorted(set(explore) | set(confirm)):
        reasons = _half_reasons(explore.get(card_id), "explore", criteria)
        reasons += _half_reasons(confirm.get(card_id), "confirm", criteria)
        passes_e = explore.get(card_id) is not None and not any(
            r.startswith("explore:") for r in reasons
        )
        passes_c = confirm.get(card_id) is not None and not any(
            r.startswith("confirm:") for r in reasons
        )
        rows.append(
            {
                "card_id": card_id,
                "passes_explore": passes_e,
                "passes_confirm": passes_c,
                "candidate": passes_e and passes_c,
                "reasons": reasons,
            }
        )
    return pa.Table.from_pylist(rows, schema=schema)

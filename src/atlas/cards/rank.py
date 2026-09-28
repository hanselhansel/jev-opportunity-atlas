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

from atlas import paths


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


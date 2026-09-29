"""Site tables from saved run outputs (``meta.mode == "real"``). No Jev calls.

``build_site_data`` reads a snapshot, a screen run, a facets run, an assign
run, the phase-2 facet sample, optional audit evaluations and a synthetic
benchmark run, and the gold labels, then writes every table in
``atlas.sitedata.tables.SITE_TABLES`` as Parquet. Three tables carry one
column beyond the contract: ``domain_share.qualifier`` (how the share was
estimated), ``quality.system`` (jev, a baseline, or the random-card control),
and ``findings.unsolved_rate`` (null unless ``replies_run`` was given). The
output must pass the release text gate before it replaces ``out_dir``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.sitedata.build_quality import (
    quality_rows,
    runs_from_phases,
    runs_rows,
)
from atlas.sitedata.inputs import _gold, _labels, _load, _meta, find_cardset
from atlas.sitedata.tables import SITE_TABLES

EXTRA_FIELDS = {
    "domain_share": [pa.field("qualifier", pa.string())],
    "quality": [pa.field("system", pa.string())],
    "findings": [
        pa.field("unsolved_rate", pa.float64()),
        pa.field("short_label", pa.string()),
    ],
    "card_share": [pa.field("short_label", pa.string())],
}
# Approved cardset text (Claude drafts, Hansel approves). The release text gate
# flags these findings columns by name or length; the build instead checks that
# every value is exactly an approved statement or group label.
CARD_TEXT_COLUMNS = ("title", "problem_statement", "user_workflow")
# Tables whose columns may hold approved cardset text (card statements, group
# labels, and short display labels from the cardset's labels.yaml). The gate
# checks every value against the cardset in meta plus the labels file.
APPROVED_TEXT_COLUMNS = {
    "findings.parquet": CARD_TEXT_COLUMNS + ("short_label",),
    "card_share.parquet": ("label", "short_label"),
}
MAX_LABEL_CHARS = 32


class SiteDataError(RuntimeError):
    pass


def site_schema(name: str) -> pa.Schema:
    schema = SITE_TABLES[name]
    for field in EXTRA_FIELDS.get(name, []):
        schema = schema.append(field)
    return schema


def load_short_labels(cardset: str) -> dict[str, dict[str, str]]:
    """Short display labels from ``configs/cards/<cardset>.labels.yaml``.

    Claude-drafted display text of at most 32 characters, keyed by group and
    card id. Returns empty maps when the file is absent; a label over the cap
    is a build error.
    """
    import yaml

    out: dict[str, dict[str, str]] = {"groups": {}, "cards": {}}
    name, _, version = cardset.partition(".")
    path = paths.CONFIGS / "cards" / f"{name}.{version}.labels.yaml"
    if not name or not version or not path.exists():
        return out
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for kind in list(out):
        for key, value in (data.get(kind) or {}).items():
            text = str(value)
            if len(text) > MAX_LABEL_CHARS:
                raise SiteDataError(
                    f"{path.name} {kind}.{key} is {len(text)} chars "
                    f"(max {MAX_LABEL_CHARS})"
                )
            out[kind][key] = text
    return out


def _gate_copy(src: Path, dest: Path) -> Path:
    """Copy of the tables with all-null string columns retyped to null.

    ``text_gate`` fails on a string column with no non-null value (it
    concatenates an empty list); such a column holds no text. Field names are
    kept, so the forbidden-field check still sees every column.
    """
    for p in sorted(src.glob("*.parquet")):
        t = pq.read_table(p)
        for i, field in enumerate(t.schema):
            if pa.types.is_string(field.type) and t.num_rows and (
                t.column(i).null_count == t.num_rows
            ):
                t = t.set_column(i, field.name, pa.nulls(t.num_rows, pa.null()))
        pq.write_table(t, dest / p.name)
    return dest


def site_text_problems(out_dir) -> list[str]:
    """Release text-gate problems, except card-text columns whose every
    value is an approved statement or group label of the cardset in meta."""
    from atlas.publication.export import text_gate

    out_dir = Path(out_dir)
    with tempfile.TemporaryDirectory() as staged:
        problems = text_gate(_gate_copy(out_dir, Path(staged)))
    meta = {
        r["key"]: r["value"]
        for r in pq.read_table(out_dir / "meta.parquet").to_pylist()
    }
    name, _, version = meta.get("cardset", "").partition(".")
    cs = find_cardset(version, name) if name and version else None
    approved = set()
    if cs is not None:
        approved = {c.statement for c in cs.all_cards.values()} | set(
            cs.groups.values()
        )
        labels = load_short_labels(meta.get("cardset", ""))
        approved |= set(labels["groups"].values()) | set(labels["cards"].values())
    ok = {}
    for rel, cols in APPROVED_TEXT_COLUMNS.items():
        path = out_dir / rel
        if cs is None or not path.exists():
            continue
        t = pq.read_table(path)
        ok[rel] = {
            col
            for col in cols
            if col in t.column_names
            and all(
                v in approved for v in t[col].to_pylist() if v is not None
            )
        }
    return [
        p
        for p in problems
        if not (
            len(p.split()) > 2
            and p.split()[2].partition(":")[2]
            in ok.get(p.split()[2].partition(":")[0], ())
        )
    ]


def build_site_data(
    out_dir,
    snapshot_id,
    screen_run,
    facets_run,
    assign_run,
    taxonomy_version,
    label_sets,
    *,
    benchmark_run=None,
    facets_set="facets@2",
    cardset=None,
    facet_sample=None,
    replies_run=None,
    robust_screen=None,
    robust_assign=None,
    run_phases=None,
    audit_runs=(),
    top_n=20,
    n_boot=2000,
    seed=0,
    built_at=None,
) -> dict:
    """Write every site table to ``out_dir``; returns row counts per table."""
    from atlas.cards.rank import load_criteria, load_weights
    from atlas.sitedata.build_card_share import card_share_rows
    from atlas.sitedata.build_cards import evidence_rows, finding_rows
    from atlas.sitedata.build_robustness import robustness_rows
    from atlas.sitedata.build_share import domain_share_rows

    if facet_sample is None:
        raise SiteDataError("facet_sample is required in real mode")
    label_sets = list(label_sets)
    built_at = built_at or datetime.now(UTC).isoformat(timespec="seconds")
    cs = find_cardset(taxonomy_version, cardset)
    ctx = _load(
        snapshot_id,
        screen_run,
        facets_run,
        assign_run,
        taxonomy_version,
        facets_set,
        cs,
        facet_sample,
    )
    fh, dom = _labels(label_sets)
    gold = _gold(label_sets, fh, dom, ctx["screen"])
    ctx.update(
        human=fh,
        facets_run=facets_run,
        assign_run=assign_run,
        question_set=facets_set,
        taxonomy_version=taxonomy_version,
    )

    # Domain share is estimated on the phase-2 pos population: one frame row
    # per screen-positive comment, carrying the phase-2 weight (w1 / p2) and
    # Jev's facet answers. ``domain_share_rows`` restricts to firsthand
    # problems (account_type == "firsthand_account") itself.
    frame = []
    for cid, f in ctx["facet"].items():
        if f.get("phase") != "pos":
            continue
        by_q = ctx["answers"].get(cid) or {}
        c = ctx["comments"].get(cid, {})
        frame.append(
            {
                "comment_id": cid,
                "story_id": f.get("story_id"),
                "stratum": f.get("stratum"),
                "weight": f.get("weight"),
                "firsthand_p": f.get("firsthand_p"),
                "period": c.get("period"),
                "domain": (by_q.get("domain") or {}).get("choice"),
                "account_type": (by_q.get("account_type") or {}).get("choice"),
            }
        )
    replies = None
    if replies_run:
        replies = pq.read_table(
            paths.run_dir(replies_run) / "replies" / "unsolved_by_problem.parquet"
        )
    findings, finding_evidence = finding_rows(
        ctx, cs, load_criteria(), load_weights(), top_n, built_at, replies=replies
    )
    short = load_short_labels(f"{cs.name}.{cs.version}")
    for f in findings:
        f["short_label"] = short["cards"].get(f["finding_id"]) or f["title"]
    ev_ids = {c for c, a in ctx["answers"].items() if a}
    ev_ids |= {r["comment_id"] for r in finding_evidence}
    snap = paths.snapshot_dir(snapshot_id)
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    args = {
        "snapshot_id": snapshot_id,
        "screen_run": screen_run,
        "facets_run": facets_run,
        "assign_run": assign_run,
        "benchmark_run": benchmark_run,
        "facet_sample": facet_sample,
        "built_at": built_at,
        "facets_set": facets_set,
        "taxonomy_version": taxonomy_version,
        "label_sets": label_sets,
        "cardset": f"{cs.name}.{cs.version}",
    }
    n = {"screened": len(ctx["screen"]), "faceted": len(ev_ids), "gold": len(gold)}
    meta = _meta(args, manifest.get("window") or {}, n)
    from atlas.sitedata.xspecs import load_x_titles

    _, run_labels = load_x_titles()
    if run_labels:
        meta["run_labels"] = json.dumps(run_labels)
    roles = [("screen", screen_run), ("facets", facets_run), ("assign", assign_run)]
    if benchmark_run:
        roles.append(("benchmark", benchmark_run))
    if replies_run:
        roles.append(("replies", replies_run))
    run_rows = runs_from_phases(run_phases) if run_phases else runs_rows(roles)
    meta["total_calculated_usd"] = str(
        round(sum(r["calculated_usd"] or 0.0 for r in run_rows), 6)
    )
    meta["total_calls"] = str(sum(r["calls"] or 0 for r in run_rows))
    tables = {
        "meta": pa.table({"key": list(meta), "value": list(meta.values())}),
        "coverage": pq.read_table(snap / "coverage.parquet")
        .select(contracts.COVERAGE.names)
        .cast(contracts.COVERAGE),
        "domain_share": domain_share_rows(
            frame, gold, screen_run, facets_set, n_boot, seed
        ),
        "card_share": card_share_rows(ctx, cs, n_boot, seed, short_labels=short),
        "robustness": robustness_rows(
            screen=(
                json.loads(Path(robust_screen).read_text(encoding="utf-8"))
                if robust_screen
                else None
            ),
            assign=(
                json.loads(Path(robust_assign).read_text(encoding="utf-8"))
                if robust_assign
                else None
            ),
        ),
        "evidence": evidence_rows(ev_ids, ctx),
        "findings": findings,
        "finding_evidence": finding_evidence,
        "runs": run_rows,
        "quality": quality_rows(
            [r for _, r in roles], label_sets, benchmark_run, audit_runs=audit_runs
        ),
    }
    return _write(Path(out_dir), tables)


def _write(out_dir: Path, tables: dict) -> dict:
    tmp = out_dir.with_name(out_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    counts = {}
    try:
        for name in SITE_TABLES:
            t = tables[name]
            schema = site_schema(name)
            if not isinstance(t, pa.Table):
                t = pa.Table.from_pylist(t, schema=schema)
            pq.write_table(t.cast(schema), tmp / f"{name}.parquet", compression="zstd")
            counts[name] = t.num_rows
        problems = site_text_problems(tmp)
        if problems:
            raise SiteDataError("site data blocked:\n" + "\n".join(problems))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp.rename(out_dir)
    return counts

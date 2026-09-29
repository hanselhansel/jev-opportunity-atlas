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
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import contracts, paths
from atlas.sitedata.build_quality import quality_rows, runs_rows
from atlas.sitedata.tables import SITE_TABLES

EXTRA_FIELDS = {
    "domain_share": [pa.field("qualifier", pa.string())],
    "quality": [pa.field("system", pa.string())],
    "findings": [pa.field("unsolved_rate", pa.float64())],
}
# Approved cardset text (Claude drafts, Hansel approves). The release text gate
# flags these findings columns by name or length; the build instead checks that
# every value is exactly an approved statement or group label.
CARD_TEXT_COLUMNS = ("title", "problem_statement", "user_workflow")
SOURCE = "Hacker News comments (official API)"


class SiteDataError(RuntimeError):
    pass


def site_schema(name: str) -> pa.Schema:
    schema = SITE_TABLES[name]
    for field in EXTRA_FIELDS.get(name, []):
        schema = schema.append(field)
    return schema


def _code_commit() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        check=False,
    )
    return proc.stdout.decode().strip() if proc.returncode == 0 else "unknown"


def find_cardset(taxonomy_version: str, cardset: str | None = None):
    from atlas.cards.engine.cardset import load_cardset

    if cardset is None:
        found = sorted((paths.CONFIGS / "cards").glob(f"*.{taxonomy_version}.yaml"))
        if len(found) != 1:
            raise SiteDataError(
                f"expected one cardset for {taxonomy_version}, found "
                f"{[p.name for p in found]}; pass cardset"
            )
        cardset = found[0].name.split(".", 1)[0]
    return load_cardset(cardset, taxonomy_version)


def _labels(label_sets) -> tuple[dict, dict]:
    """(firsthand label per comment, domain label per comment), latest wins."""
    from atlas.evaluation import exclusions
    from atlas.evaluation.store import labels_path

    fh, dom = {}, {}
    if not labels_path().exists():
        return fh, dom
    for ls in label_sets:
        primary, _ = exclusions.latest(labels_path(), ls)
        for (cid, q), row in primary.items():
            if q == "firsthand_problem":
                fh[int(cid)] = row["value"]
            elif q == "domain":
                dom[int(cid)] = row["value"]
    return fh, dom


def _gold(label_sets, fh, dom, screen) -> dict:
    """Gold items usable for PPI: drawn with a known probability, in the sample,
    with a yes/no firsthand label and a domain label on every yes."""
    path = paths.LABELS / "gold_draws.parquet"
    if not path.exists():
        return {}
    sel = {}
    for r in pq.read_table(path).to_pylist():
        if r["label_set"] in label_sets and r["selection_prob"]:
            sel.setdefault(int(r["comment_id"]), float(r["selection_prob"]))
    gold = {}
    for cid, p in sel.items():
        value = fh.get(cid)
        if cid not in screen or value not in ("yes", "no"):
            continue
        if value == "yes" and cid not in dom:
            continue
        gold[cid] = {"fh": value == "yes", "domain": dom.get(cid), "sel": p}
    return gold


def _load(
    snapshot_id, screen_run, facets_run, assign_run, tv, facets_set, cs, facet_sample
):
    from atlas.cards.engine import assign

    screen = {
        r["comment_id"]: r
        for r in pq.read_table(
            paths.run_dir(screen_run) / "screen_by_comment.parquet"
        ).to_pylist()
    }
    answers = assign.read_answers(paths.run_dir(facets_run), facets_set)
    rows = assign.load_assignments(paths.run_dir(assign_run), tv).rows
    assigned = {}
    for r in rows:
        card = r.get("card_id")
        if card not in (None, "none") and card in cs.all_cards:
            r = {**r, "card_id": cs.resolve(card)}
        assigned[int(r["comment_id"])] = r
    # Phase-2 facet sample: comment_id -> phase (pos|neg) and the correct
    # weight for any faceted or assigned comment (w1 / p2).
    facet = {
        int(r["comment_id"]): r
        for r in pq.read_table(paths.sample_path(facet_sample)).to_pylist()
    }
    ids = sorted(set(screen) | set(answers) | set(assigned) | set(facet))
    comments = pq.read_table(
        paths.snapshot_dir(snapshot_id) / "comments.parquet",
        columns=["id", "author", "story_id", "period", "thread_type", "text_sha256"],
        filters=[("id", "in", ids)],
    ).to_pylist()
    return {
        "screen": screen,
        "answers": answers,
        "assign": assigned,
        "comments": {r["id"]: r for r in comments},
        "facet": facet,
    }


def _meta(args: dict, window: dict, n: dict) -> dict:
    return {
        "mode": "real",
        "snapshot_id": args["snapshot_id"],
        "run_id": args["screen_run"],
        "screen_run": args["screen_run"],
        "facets_run": args["facets_run"],
        "assign_run": args["assign_run"],
        "benchmark_run": args["benchmark_run"] or "",
        "facet_sample": args["facet_sample"],
        "window_start": window.get("start", ""),
        "window_end": window.get("end", ""),
        "built_at": args["built_at"],
        "code_commit": _code_commit(),
        "question_set": args["facets_set"],
        "taxonomy_version": args["taxonomy_version"],
        "cardset": args["cardset"],
        "label_sets": ",".join(args["label_sets"]),
        "n_screened": str(n["screened"]),
        "n_faceted": str(n["faceted"]),
        "n_gold": str(n["gold"]),
        "lane": "breadth",
        "source": SOURCE,
    }


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
    """Release text-gate problems, except findings card-text columns whose every
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
    findings = pq.read_table(out_dir / "findings.parquet")
    ok = {
        col
        for col in CARD_TEXT_COLUMNS
        if cs is not None
        and all(v in approved for v in findings[col].to_pylist() if v is not None)
    }
    return [
        p
        for p in problems
        if not (
            len(p.split()) > 2
            and p.split()[2].partition(":")[0] == "findings.parquet"
            and p.split()[2].partition(":")[2] in ok
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
    top_n=20,
    n_boot=2000,
    seed=0,
    built_at=None,
) -> dict:
    """Write every site table to ``out_dir``; returns row counts per table."""
    from atlas.cards.rank import load_criteria, load_weights
    from atlas.sitedata.build_cards import evidence_rows, finding_rows
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
    roles = [("screen", screen_run), ("facets", facets_run), ("assign", assign_run)]
    if benchmark_run:
        roles.append(("benchmark", benchmark_run))
    if replies_run:
        roles.append(("replies", replies_run))
    tables = {
        "meta": pa.table({"key": list(meta), "value": list(meta.values())}),
        "coverage": pq.read_table(snap / "coverage.parquet")
        .select(contracts.COVERAGE.names)
        .cast(contracts.COVERAGE),
        "domain_share": domain_share_rows(
            frame, gold, screen_run, facets_set, n_boot, seed
        ),
        "evidence": evidence_rows(ev_ids, ctx),
        "findings": findings,
        "finding_evidence": finding_evidence,
        "runs": runs_rows(roles),
        "quality": quality_rows([r for _, r in roles], label_sets, benchmark_run),
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

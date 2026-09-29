"""Input loading for :func:`atlas.sitedata.build.build_site_data`.

Everything here reads the upstream artifacts the site build combines: the
cardset, the label store, the gold draws, the screen/facets/assign run
outputs, the phase-2 facet sample, and the snapshot comments. ``_meta`` then
packs the provenance record written to ``meta.parquet``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from atlas import paths

SOURCE = "Hacker News comments (official API)"


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
    from atlas.sitedata.build import SiteDataError

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

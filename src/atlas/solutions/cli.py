"""`atlas solutions run` (S5): named fixes over an assign run.

Dictionary-matches configs/tools.v1.yaml names in the problem comments of
the top cards and in their direct replies and author follow-ups. Problem
mentions count as complaints; reply-side mentions get one Jev confirm call
per (reply, tool). Writes <assign run>/solutions/{mentions.parquet,
answers/, tallies.json}; reruns resume through the runner's done set.
`section` is the `story data --with tools` entry point S1's SECTIONS table
registers.
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.cards import replies as replies_mod
from atlas.cards import replies_run
from atlas.cards.engine import cli as cards_cli
from atlas.cards.engine.assign import load_assignments
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.runner import (
    BudgetStopped,
    RunContext,
    raise_for_stopped,
    run_batch,
)
from atlas.solutions import confirm, match, tally

MODEL = "jev-1.13.0"
MIN_CARD_P = 0.5
MAX_REPLIES = 5
DEFAULT_SAMPLE = "main-facets-20260930x"


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def register(sub) -> None:
    parser = sub.add_parser("solutions", help="named-fix tallies over an assign run")
    commands = parser.add_subparsers(dest="solutions_command", required=True)

    rp = commands.add_parser("run", help="match tool names, Jev-confirm reply hits")
    rp.add_argument("--assign-run", required=True, help="assign run id")
    rp.add_argument(
        "--version",
        default=None,
        help="taxonomy version (default: the single assignments file)",
    )
    rp.add_argument(
        "--snapshot", default=None, help="Default: configs/acquisition.toml"
    )
    rp.add_argument(
        "--sample",
        default=DEFAULT_SAMPLE,
        help="phase-2 sample id; supplies bootstrap strata",
    )
    rp.add_argument("--top-cards", type=int, default=40)
    rp.add_argument("--tools", default=None, help="default configs/tools.v1.yaml")
    rp.add_argument("--budget", default="solutions")
    rp.add_argument("--rpm", type=float, default=1000)
    rp.add_argument("--concurrency", type=int, default=8)
    rp.add_argument("--yes", action="store_true")
    rp.set_defaults(func=_cmd_run)


def _default_snapshot() -> str:
    cfg = tomllib.loads((paths.CONFIGS / "acquisition.toml").read_text())
    return cfg["snapshot_id"]


def _assign_version(run_dir: Path, requested) -> str:
    if requested:
        return requested
    found = sorted(run_dir.glob("assignments-*.parquet"))
    if len(found) != 1:
        raise SystemExit(
            f"{run_dir}: {len(found)} assignments-*.parquet files; "
            "pass --version"
        )
    return found[0].stem.rsplit("-", 1)[1]


def _problem_cards(rows, top_cards, min_card_p=MIN_CARD_P) -> dict:
    """comment_id -> card_id for qualifying assignments on the top cards."""
    qual = [
        r
        for r in rows
        if r.get("card_id") not in (None, "none")
        and (r.get("card_p") or 0.0) >= min_card_p
    ]
    if top_cards is not None:
        counts = Counter(r["card_id"] for r in qual)
        keep = {
            cid
            for cid, _n in sorted(
                counts.items(), key=lambda kv: (-kv[1], kv[0])
            )[:top_cards]
        }
        qual = [r for r in qual if r["card_id"] in keep]
    return {int(r["comment_id"]): r["card_id"] for r in qual}


def _snapshot_meta(snapshot_dir, ids) -> dict:
    """comment id -> {story_id, time, text} for arbitrary comment ids."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    parquet = Path(snapshot_dir) / "comments.parquet"
    if not parquet.exists():
        raise FileNotFoundError(parquet)
    import duckdb

    wanted = pa.table({"id": pa.array(ids, type=pa.int64())})
    con = duckdb.connect()
    try:
        con.register("wanted", wanted)
        rows = con.execute(
            """
            select c.id, c.story_id, c.time, c.text_norm
            from read_parquet(?) c join wanted w on w.id = c.id
            """,
            [str(parquet)],
        ).fetchall()
    finally:
        con.close()
    return {r[0]: {"story_id": r[1], "time": r[2], "text": r[3]} for r in rows}


def _strata(sample_id) -> dict:
    """problem comment_id -> phase-2 stratum from the facet sample."""
    path = paths.sample_path(sample_id)
    if not path.exists():
        return {}
    rows = pq.read_table(path, columns=["comment_id", "stratum"]).to_pylist()
    return {int(r["comment_id"]): r["stratum"] for r in rows}


def collect_mentions(
    snapshot_dir, problem_cards, pain, tools, strata, max_replies=MAX_REPLIES
) -> list[dict]:
    """One mention row per (comment, tool) over problems and their replies.

    kinds: "problem" (the complaint context, free), "reply" and "followup"
    (fix candidates, confirmed by Jev). Rows carry text/pain for item
    building; mentions.parquet keeps only the MENTIONS columns.
    """
    matcher = match.compile_tools(tools)
    pairs = replies_mod.reply_pairs(
        snapshot_dir, problem_cards.keys(), max_replies=max_replies
    )
    reply_ids = [p["reply_id"] for p in pairs.pairs] + [
        f["reply_id"] for f in pairs.author_followups
    ]
    meta = _snapshot_meta(snapshot_dir, set(problem_cards) | set(reply_ids))

    mentions = []

    def _add(comment_id, problem_id, kind, text, time, story_id, extra):
        for name in sorted(matcher.find(text)):
            mentions.append(
                {
                    "hit_id": confirm.hit_id(comment_id, name),
                    "comment_id": comment_id,
                    "problem_id": problem_id,
                    "card_id": problem_cards[problem_id],
                    "story_id": story_id,
                    "kind": kind,
                    "tool": name,
                    "time": time,
                    "stratum": strata.get(problem_id, "unsampled"),
                    **extra,
                }
            )

    for pid in sorted(problem_cards):
        row = meta.get(pid) or {}
        _add(
            pid,
            pid,
            "problem",
            row.get("text"),
            row.get("time"),
            row.get("story_id"),
            {"text": None, "pain": None},
        )
    for kind, seq in (
        ("reply", pairs.pairs),
        ("followup", pairs.author_followups),
    ):
        for p in seq:
            pid = p["problem_id"]
            if pid not in pain:
                continue
            story = (meta.get(p["reply_id"]) or {}).get("story_id")
            if story is None:
                story = (meta.get(pid) or {}).get("story_id")
            _add(
                p["reply_id"],
                pid,
                kind,
                p["text"],
                p["time"],
                story,
                {"text": p["text"], "pain": pain[pid]},
            )
    return mentions


async def _run(ctx, items) -> dict | None:
    if not items:
        return None
    out = await run_batch(ctx, items, confirm.question_set())
    raise_for_stopped(ctx, out, len(items))
    return out


def _run_ctx(args, price_row, cap, worst, usd_per_token, run_dir) -> RunContext:
    guard = BudgetGuard.for_budget(args.budget, cap, usd_per_token, worst)
    try:
        client = JevClient(
            api_key=keys.get_api_key(),
            base=keys.base_url(),
            transport=_transport(),
        )
        return RunContext(
            run_id=args.assign_run,
            client=client,
            guard=guard,
            model=MODEL,
            price_version=price_row["version"],
            run_dir=run_dir,
            budget=args.budget,
            rpm=args.rpm,
            concurrency=args.concurrency,
        )
    except BaseException:
        guard.close()
        raise


def _cmd_run(args) -> None:
    budgets, price_row, usd_per_token = cards_cli._load_configs()
    cap, worst = cards_cli._budget_cap(budgets, args.budget)
    run_dir = paths.run_dir(args.assign_run)
    version = _assign_version(run_dir, args.version)
    result = load_assignments(run_dir, version)
    pain = {
        r["comment_id"]: r["pain_sentence"]
        for r in pq.read_table(run_dir / "pain.parquet").to_pylist()
    }
    problem_cards = _problem_cards(result.rows, args.top_cards)
    tools = match.load_tools(args.tools or paths.CONFIGS / "tools.v1.yaml")
    mentions = collect_mentions(
        paths.snapshot_dir(args.snapshot or _default_snapshot()),
        problem_cards,
        pain,
        tools,
        _strata(args.sample),
    )
    hits = [m for m in mentions if m["kind"] in ("reply", "followup")]
    items = confirm.confirm_items(hits)
    tokens = [replies_run.item_tokens(it) for it in items]
    cards_cli._print_estimate(
        "solutions", {"solutions": tokens}, args.budget, cap, usd_per_token
    )
    if not args.yes:
        return
    out_dir = run_dir / "solutions"
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token, out_dir)
    try:
        asyncio.run(_run(ctx, items))
    except BudgetStopped as exc:
        exc.fail()
    finally:
        ctx.guard.close()
    answers = replies_run.answers_table(out_dir)
    confirmed = confirm.confirmed_ids(answers)
    tools_rows, card_tools = tally.tally(mentions, confirmed, tools)
    tally.write_mentions(mentions, out_dir / "mentions.parquet")
    meta = {
        "assign_run": args.assign_run,
        "version": version,
        "snapshot": args.snapshot or _default_snapshot(),
        "sample": args.sample,
        "top_cards": args.top_cards,
        "n_problems": len(problem_cards),
        "n_hits": len(items),
        "n_confirmed": len(confirmed),
    }
    tally.write_tallies(out_dir / "tallies.json", tools_rows, card_tools, meta)
    print(
        json.dumps(
            {
                "problems": len(problem_cards),
                "hits": len(items),
                "confirmed": len(confirmed),
                "tools": len(tools_rows),
                "out": str(out_dir),
            },
            indent=1,
        )
    )


def section(args, story_path) -> None:
    """`story data --with tools`: merge `tools` and per-card `tools`.

    Registered by S1's story.cli.SECTIONS; imports atlas.story lazily so
    this module loads before that lane exists.
    """
    from atlas.story import io

    path = paths.run_dir(args.assign_run) / "solutions" / "tallies.json"
    tallies = json.loads(path.read_text(encoding="utf-8"))
    io.merge_section(story_path, "tools", tallies["tools"])
    story = json.loads(Path(story_path).read_text(encoding="utf-8"))
    by_id = tallies.get("cards_tools", {})
    for card in story.get("cards", []):
        if card.get("id") in by_id:
            card["tools"] = by_id[card["id"]]
    io.merge_section(story_path, "cards", story.get("cards", []))

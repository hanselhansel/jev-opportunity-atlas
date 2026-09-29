"""`atlas builders` commands: draw the Show HN launch sample and assign it
to the need cards.

Every Jev command prints a cost estimate first and requires --yes. The API
key is read only through atlas.inference.keys at call time. `story data
--with builders` reaches `story_section` through atlas.story.cli.SECTIONS.
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas import paths
from atlas.builders import run as builders_run
from atlas.builders import sample, shares
from atlas.cards.engine import cli as cards_cli
from atlas.cards.engine.assign import (
    card_item,
    group_item,
    write_assignments,
)
from atlas.cards.engine.cardset import load_cardset
from atlas.cards.engine.combine import PAIN_SCHEMA
from atlas.inference import keys
from atlas.inference.budget import BudgetGuard
from atlas.inference.client import JevClient
from atlas.inference.runner import BudgetStopped, RunContext

MODEL = "jev-1.13.0"


def _transport():
    """Transport override point for tests; None means real httpx."""
    return


def _default_snapshot() -> str:
    cfg = tomllib.loads(
        (paths.CONFIGS / "acquisition.toml").read_text(encoding="utf-8")
    )
    return cfg["snapshot_id"]


def _run_ctx(args, price_row, cap, worst, usd_per_token) -> RunContext:
    guard = BudgetGuard.for_budget(args.budget, cap, usd_per_token, worst)
    try:
        client = JevClient(
            api_key=keys.get_api_key(),
            base=keys.base_url(),
            transport=_transport(),
        )
        return RunContext(
            run_id=args.run,
            client=client,
            guard=guard,
            model=MODEL,
            price_version=price_row["version"],
            run_dir=paths.run_dir(args.run),
            budget=args.budget,
            rpm=args.rpm,
            concurrency=args.concurrency,
        )
    except BaseException:
        guard.close()
        raise


def _launch_tokens(rows, cs) -> dict[str, list[int]]:
    """Estimated tokens per level under the launch instructions; the card
    column is an upper bound since level 2 skips group-none rows."""
    biggest = max(cs.groups, key=lambda g: len(cs.cards_in(g)))
    out = {"assign_group": [], "assign_card": []}
    for r in rows:
        out["assign_group"].append(
            cards_cli._est_tokens(
                group_item(
                    r["comment_id"],
                    r["pain_sentence"],
                    r["sentences"],
                    cs,
                    instructions=builders_run.GROUP_INSTRUCTIONS,
                )
            )
        )
        out["assign_card"].append(
            cards_cli._est_tokens(
                card_item(
                    r["comment_id"],
                    r["pain_sentence"],
                    r["sentences"],
                    cs,
                    biggest,
                    instructions=builders_run.CARD_INSTRUCTIONS,
                )
            )
        )
    return out


def _run_or_exit(coro):
    try:
        return asyncio.run(coro)
    except BudgetStopped as exc:
        exc.fail()


def _cmd_draw(args) -> None:
    snapshot = args.snapshot or _default_snapshot()
    table = sample.draw_launches(snapshot, n=args.n, seed=args.seed)
    sample_id = sample.sample_id_for(args.seed)
    sidecar = paths.SAMPLES / f"{sample_id}.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "sample_id": sample_id,
                "n": table.num_rows,
                "population": meta["population"],
                "path": str(paths.sample_path(sample_id)),
                "sha256": meta["sha256"],
            },
            sort_keys=True,
        )
    )


def _cmd_run(args) -> None:
    budgets, price_row, usd_per_token = cards_cli._load_configs()
    cap, worst = cards_cli._budget_cap(budgets, args.budget)
    cs = load_cardset(args.cardset, args.version)
    sample_id = args.sample or args.run
    table = pq.read_table(paths.sample_path(sample_id))
    snapshot = args.snapshot or _default_snapshot()
    rows = builders_run.launch_items(table, snapshot)
    cards_cli._print_estimate(
        "builders", _launch_tokens(rows, cs), args.budget, cap, usd_per_token
    )
    if not args.yes:
        return
    ctx = _run_ctx(args, price_row, cap, worst, usd_per_token)
    try:
        result = _run_or_exit(builders_run.assign_launches(ctx, rows, cs))
        run_dir = paths.run_dir(args.run)
        run_dir.mkdir(parents=True, exist_ok=True)
        pain = [
            {
                "comment_id": r["comment_id"],
                "pain_sentence": r["pain_sentence"],
            }
            for r in rows
        ]
        pq.write_table(
            pa.Table.from_pylist(pain, schema=PAIN_SCHEMA),
            str(run_dir / "pain.parquet"),
        )
        write_assignments(run_dir, result, cs.version)
        (run_dir / "builders.json").write_text(
            json.dumps(
                {
                    "run_id": args.run,
                    "sample_id": sample_id,
                    "snapshot": snapshot,
                    "cardset": args.cardset,
                    "version": cs.version,
                    "items": len(rows),
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        ctx.guard.close()
    print(
        json.dumps(
            {"run": args.run, "items": len(rows), "assigned": len(result.rows)},
            sort_keys=True,
        )
    )


def _story_io():
    from atlas.story import io

    return io


def _complaint_reps(args, card_ids) -> dict:
    """card_id -> {"est", "reps"}: weighted share of firsthand problems on
    the card, with replicates from the S1 stratified thread bootstrap."""
    import numpy as np

    from atlas.story import boot, frame

    snapshot = getattr(args, "snapshot", None) or _default_snapshot()
    fr = frame.load_frame(
        getattr(args, "facet_sample", None) or "main-facets-20260930x",
        getattr(args, "facets_run", None) or "main-facets-20260930",
        getattr(args, "assign_run", None) or "main-cards-final2-t3",
        snapshot,
        cardset="main",
        version="t3",
    )
    fh = fr[fr["firsthand"]]
    if not card_ids or len(fh) == 0:
        return {}
    rep = boot.Replicates(fh, R=shares.R_DEFAULT, seed=shares.SEED)
    card_col = fh["card"].to_numpy()
    w = fh["weight"].to_numpy(dtype=np.float64)
    X = np.column_stack(
        [(card_col == c).astype(np.float64) for c in card_ids]
    )
    num = np.asarray(rep.totals(X), dtype=np.float64)
    den = np.asarray(
        rep.totals(np.ones((len(fh), 1))), dtype=np.float64
    )[:, 0]
    den = np.where(den > 0.0, den, np.nan)
    total = float(w.sum())
    return {
        c: {
            "est": float(w @ X[:, j]) / total,
            "reps": num[:, j] / den,
        }
        for j, c in enumerate(card_ids)
    }


def story_section(args, story_path) -> None:
    """`story data --with builders`: merge `builders` and `cards[].builders`."""
    io = _story_io()
    run_id = getattr(args, "builders_run", None) or sample.sample_id_for(
        sample.DEFAULT_SEED
    )
    run_dir = paths.run_dir(run_id)
    meta_path = run_dir / "builders.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8"))
        if meta_path.exists()
        else {}
    )
    version = meta.get("version") or getattr(args, "version", None) or "t3"
    sample_id = meta.get("sample_id") or run_id
    assign_rows = pq.read_table(
        run_dir / f"assignments-{version}.parquet"
    ).to_pylist()
    sample_table = pq.read_table(paths.sample_path(sample_id))
    story = json.loads(Path(story_path).read_text(encoding="utf-8"))
    card_ids = [c["id"] for c in story.get("cards", [])]
    story_cards = _complaint_reps(args, card_ids)
    builders, per_card = shares.builder_shares(
        assign_rows, sample_table, story_cards
    )
    io.merge_section(Path(story_path), "builders", builders)
    if card_ids:
        for entry in story["cards"]:
            entry["builders"] = per_card.get(entry["id"])
        io.merge_section(Path(story_path), "cards", story["cards"])


def _register_story_section() -> None:
    try:
        from atlas.story.cli import SECTIONS
    except ImportError:
        return
    SECTIONS.setdefault("builders", story_section)


def register(sub) -> None:
    parser = sub.add_parser(
        "builders", help="Show HN launch sample and card assign"
    )
    commands = parser.add_subparsers(dest="builders_command", required=True)

    d = commands.add_parser(
        "draw", help="month-stratified sample of in-window Show HN stories"
    )
    d.add_argument("--n", type=int, default=sample.DEFAULT_N)
    d.add_argument("--seed", type=int, default=sample.DEFAULT_SEED)
    d.add_argument(
        "--snapshot", default=None, help="default: configs/acquisition.toml"
    )
    d.set_defaults(func=_cmd_draw)

    r = commands.add_parser(
        "run", help="assign sampled launches to the need cards"
    )
    r.add_argument("--cardset", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--run", required=True)
    r.add_argument(
        "--sample", default=None, help="sample id; default: the run id"
    )
    r.add_argument(
        "--snapshot", default=None, help="default: configs/acquisition.toml"
    )
    r.add_argument("--budget", default="builders")
    r.add_argument("--rpm", type=float, default=1000)
    r.add_argument("--concurrency", type=int, default=8)
    r.add_argument("--yes", action="store_true")
    r.set_defaults(func=_cmd_run)

    _register_story_section()


_register_story_section()

"""`atlas story data` builds story.json sections; `atlas story check` gates it.

``data`` loads the phase-2 frame, computes the S1 core sections, and writes
every key through ``io.merge_section`` so later lanes can add theirs without
rewriting the file. ``SECTIONS`` is the registry: later lanes add entries
``name -> fn(args, story_path)``, run via ``--with <name>`` (repeatable)
after the core keys, or alone via ``--only-with``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas import paths

SECTIONS: dict[str, object] = {}

DEFAULTS = {
    "facet_sample": "main-facets-20260930x",
    "facets_run": "main-facets-20260930",
    "assign_run": "main-cards-final2-t3",
    "audit_run": "pilot-20260929-cards",
    "benchmark_run": "main-benchmark-20260930",
    "robust_screen": "runs/robust-screen-compare.json",
    "robust_assign": "runs/robust-assign-compare.json",
    "run_phases": "configs/run_phases.toml",
}


def _default_snapshot() -> str:
    import tomllib

    cfg = tomllib.loads((paths.CONFIGS / "acquisition.toml").read_text())
    return cfg["snapshot_id"]


def _screen_run(facet_sample: str) -> str | None:
    sidecar = paths.SAMPLES / f"{facet_sample}.json"
    if sidecar.exists():
        return json.loads(sidecar.read_text()).get("parent_run")
    return None


def _runs_map(args) -> dict:
    """meta.runs: the runs this build consumed, by role."""
    from atlas.story.method import run_phases

    phases = run_phases(args.run_phases)
    by_phase: dict[str, list[str]] = {}
    for rid, phase in phases.items():
        by_phase.setdefault(phase, []).append(rid)

    def _one(phase, fallback=None):
        ids = by_phase.get(phase) or []
        return ids[-1] if ids else fallback

    return {
        "screen": _screen_run(args.facet_sample),
        "facets": args.facets_run,
        "assign": args.assign_run,
        "replies": _one("replies", f"{args.assign_run}/replies"),
        "solutions": _one("solutions"),
        "builders": _one("builders"),
    }


def _data(args) -> None:
    from atlas.story import core, frame, io
    from atlas.story import method as story_method

    out = Path(args.out)
    if not args.only_with:
        snapshot = args.snapshot or _default_snapshot()
        fr = frame.load_frame(
            args.facet_sample,
            args.facets_run,
            args.assign_run,
            snapshot,
            cardset=args.cardset,
            version=args.version,
        )
        sections = core.build_core(
            fr,
            snapshot,
            screen_run=_screen_run(args.facet_sample),
            R=args.R,
            seed=args.seed,
        )
        sections["meta"] = core.build_meta(
            snapshot, _runs_map(args), args.version
        )
        sections["method"] = story_method.build_method(
            args.run_phases,
            args.audit_run,
            args.benchmark_run,
            args.robust_screen,
            args.robust_assign,
        )
        for key, value in sections.items():
            io.merge_section(out, key, value)
    for name in args.with_:
        if name not in SECTIONS:
            raise SystemExit(f"unknown story section: {name}")
        SECTIONS[name](args, out)
    print(f"story data: wrote {out}")


def _check(args) -> None:
    from atlas.story.check import check_story

    problems = check_story(args.path)
    if problems:
        for p in problems:
            print(f"story check: {p}")
        raise SystemExit(1)
    print("story: ok")


def register(sub) -> None:
    story = sub.add_parser("story", help="Build and check the story.json feed")
    ssub = story.add_subparsers(dest="story_cmd", required=True)
    d = ssub.add_parser("data", help="Write story.json sections")
    d.add_argument("--out", required=True, help="story.json path")
    d.add_argument(
        "--snapshot", default=None, help="Default: configs/acquisition.toml"
    )
    d.add_argument("--facet-sample", default=DEFAULTS["facet_sample"])
    d.add_argument("--facets-run", default=DEFAULTS["facets_run"])
    d.add_argument("--assign-run", default=DEFAULTS["assign_run"])
    d.add_argument("--cardset", default="main")
    d.add_argument("--version", default="t3")
    d.add_argument("--audit-run", default=DEFAULTS["audit_run"])
    d.add_argument("--benchmark-run", default=DEFAULTS["benchmark_run"])
    d.add_argument("--robust-screen", default=DEFAULTS["robust_screen"])
    d.add_argument("--robust-assign", default=DEFAULTS["robust_assign"])
    d.add_argument("--run-phases", default=DEFAULTS["run_phases"])
    d.add_argument("--R", type=int, default=1000)
    d.add_argument("--seed", type=int, default=0)
    d.add_argument(
        "--with",
        dest="with_",
        action="append",
        default=[],
        help="Registered extra section to run (repeatable)",
    )
    d.add_argument(
        "--only-with",
        action="store_true",
        help="Skip the core rebuild; run only --with sections",
    )
    d.set_defaults(func=_data)
    c = ssub.add_parser("check", help="Gate story.json on the vocabulary rules")
    c.add_argument("path", help="story.json path")
    c.set_defaults(func=_check)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="atlas")
    sub = parser.add_subparsers(dest="cmd", required=True)
    register(sub)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

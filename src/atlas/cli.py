"""Command-line entry point: `uv run atlas <command>`.

Each subsystem owns a module with `register(subparsers)`. Every lane module is already
listed below, so lanes never edit this file. A module that is not built yet is skipped;
a module that fails to load is reported without breaking the other commands.
"""

from __future__ import annotations

import argparse
import importlib
import sys

COMMAND_MODULES = (
    "atlas.sources.cli_acquire",
    "atlas.sources.cli_snapshot",
    "atlas.sampling.cli",
    "atlas.inference.cli",
    "atlas.evaluation.cli",
    "atlas.publication.cli",
    "atlas.sitedata.cli",
    "atlas.pilot.cli",
    "atlas.discovery.cli",
    "atlas.cards.engine.cli",
    "atlas.screen.cli",
    "atlas.benchmark.cli",
    "atlas.facets.cli",
    "atlas.timeline",
)


def _not_built_yet(name: str, exc: ModuleNotFoundError) -> bool:
    return exc.name is not None and (
        name == exc.name or name.startswith(exc.name + ".")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in COMMAND_MODULES:
        try:
            module = importlib.import_module(name)
            module.register(sub)
        except ModuleNotFoundError as exc:
            if _not_built_yet(name, exc):
                continue
            print(
                f"command unavailable: {name}: {type(exc).__name__}; run uv sync --all-groups",
                file=sys.stderr,
            )
        except ImportError as exc:
            print(
                f"command unavailable: {name}: {type(exc).__name__}; run uv sync --all-groups",
                file=sys.stderr,
            )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

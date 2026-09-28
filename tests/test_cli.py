import sys
import types

from atlas import cli


def test_registry_lists_every_lane_module_once():
    assert "atlas.sources.cli_acquire" in cli.COMMAND_MODULES
    assert "atlas.discovery.cli" in cli.COMMAND_MODULES
    assert len(set(cli.COMMAND_MODULES)) == len(cli.COMMAND_MODULES)


def test_missing_module_or_parent_package_is_skipped(monkeypatch):
    monkeypatch.setattr(
        cli, "COMMAND_MODULES", ("atlas.does_not_exist", "atlas.nopkg.cli")
    )
    parser = cli.build_parser()
    assert parser.prog == "atlas"


def test_broken_lane_module_does_not_break_other_commands(monkeypatch, capsys):
    broken = types.ModuleType("atlas._broken_lane")

    def register(sub):
        raise ImportError("streamlit missing")

    broken.register = register
    monkeypatch.setitem(sys.modules, "atlas._broken_lane", broken)
    monkeypatch.setattr(
        cli, "COMMAND_MODULES", ("atlas._broken_lane", "atlas.sources.cli_acquire")
    )
    parser = cli.build_parser()
    args = parser.parse_args(["acquire", "--workers", "3"])
    assert args.workers == 3
    assert "command unavailable: atlas._broken_lane" in capsys.readouterr().err

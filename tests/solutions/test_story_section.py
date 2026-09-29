"""`story data --with tools` finds the solutions section in the registry."""

import atlas.solutions.cli as solutions_cli
from atlas.story.cli import SECTIONS


def test_tools_section_registered():
    assert SECTIONS.get("tools") is solutions_cli.section

"""Labeler audit modes. Each module defines a mode's label set, radio
questions, free-text questions, and whether the app loads comment text."""

from atlas.evaluation.modes import assignment, facets, interview, merge

MODES = {
    "facet_audit": facets,
    "assignment_audit": assignment,
    "merge_audit": merge,
    "interview": interview,
}


def get(label_set: str | None):
    """The mode module for a label set, or None for non-mode sets."""
    return MODES.get(label_set)

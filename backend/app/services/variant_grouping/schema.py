"""Inputs and outputs of variant grouping (design/variant-grouping.md §2–3)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable
from dataclasses import dataclass, field

from .walk import FolderDecision


@dataclass(frozen=True)
class GroupingFile[K: Hashable]:
    """A file to group: a caller's key and its path relative to the import root, "/"-separated."""

    key: K
    path: str


@dataclass
class ProposedGroup[K: Hashable]:
    """One variant group.

    ``subgroups`` labels the files of named sub-groups (joined child folders, or levels such as
    "Floor 2"); files of a group's main body, and of groups without sub-groups, are absent.
    ``reasons`` counts the joins that built the group by rule (``walk`` module docstring).
    ``name_is_identity`` is False when the name is a fallback (a numbering such as
    ``IMG 0001``): such names should not be matched against existing gallery groups.
    """

    keys: list[K]
    name: str
    author: str | None
    name_is_identity: bool = True
    subgroups: dict[K, str] = field(default_factory=dict)
    reasons: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class Suggestion:
    """A join the walk deliberately did not make, between two groups (indices into ``groups``)."""

    a: int
    b: int
    reason: str


@dataclass
class Grouping[K: Hashable]:
    """The result of a grouping run. Deterministic and independent of input order.

    ``decisions`` maps each effective folder ("/"-joined canonical names; "" is the root) to
    what the walk decided there, for DEBUG logging.
    """

    groups: list[ProposedGroup[K]]
    suggestions: list[Suggestion] = field(default_factory=list)
    decisions: dict[str, FolderDecision] = field(default_factory=dict)

    def group_index(self) -> dict[K, int]:
        """Key -> index of its group."""
        return {key: g for g, group in enumerate(self.groups) for key in group.keys}

    def debug_lines(self) -> list[str]:
        """One line per folder decision, then one per suggestion, for DEBUG logging."""
        lines = [d.summary() for _, d in sorted(self.decisions.items())]
        lines += [
            f"suggest: {self.groups[s.a].name!r} + {self.groups[s.b].name!r} ({s.reason})"
            for s in self.suggestions
        ]
        return lines

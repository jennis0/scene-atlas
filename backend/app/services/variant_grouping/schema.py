"""Data of variant grouping: the inputs and outputs of a run, and what the walk hands to naming."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from . import names as N
from .names import Folder, NameEvidence
from .tree import EffectiveTree


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


class FolderReason(Enum):
    """Why the walk made a folder a container (or, for ``LOCATION``, did not)."""

    ROOT = "root"
    GENERIC = "generic name"
    RECURRING = "recurring name (author/topic folder)"
    KNOWN_AUTHOR = "known author"
    HOUSE_PREFIX = "house-prefix name (author/collection folder)"
    PACK = "pack"  # only child folders, each a map of its own, of different productions
    OVER_CAP = "safety cap"  # more units than ``max_units``
    LOCATION = "candidate location"  # not a container: its units may join


@dataclass(frozen=True)
class FolderVerdict:
    """What the walk decided an effective folder is."""

    container: bool  # it sealed its subtree
    reason: FolderReason
    named_after_files: bool  # its own name is its files' common name
    variant_only: bool  # a6: a named folder of files without identity, so one map
    files: int  # files in its subtree


@dataclass
class FolderDecision:
    """How the walk decided at one effective folder, in words (for DEBUG logging)."""

    folder: str
    container: bool = False
    why: str = ""
    names: str = ""
    units_before: int = 0
    units_after: int = 0
    joins: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        kind = "container" if self.container else "meaningful"
        joins = ", ".join(f"{k} ×{v}" for k, v in sorted(self.joins.items())) or "none"
        notes = "; ".join(self.notes)
        return (
            f"{self.folder or '(root)'}: {kind} ({self.why}); units "
            f"{self.units_before} -> {self.units_after}; {self.names}; joins: {joins}"
            + (f"; {notes}" if notes else "")
        )


@dataclass
class Grouping[K: Hashable]:
    """The result of a grouping run. Deterministic and independent of input order.

    ``folders`` is the walk's verdict on each effective folder (canonical name tuples; ``()`` is
    the root). ``decisions`` describes the same folders in words, keyed "/"-joined, for DEBUG
    logging.
    """

    groups: list[ProposedGroup[K]]
    suggestions: list[Suggestion] = field(default_factory=list)
    folders: dict[Folder, FolderVerdict] = field(default_factory=dict)
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


# ----------------------------------------------------------------------------- walk -> naming


@dataclass(frozen=True)
class SubLabel:
    """A file's sub-group within its group: a joined child folder, or a level from its name."""

    kind: str  # "folder" (effective child folder) or "level" (floor#2, roof, ...)
    value: Folder | str


@dataclass
class WalkFiles:
    """Per-file inputs of the walk, in walk order."""

    folders: list[Folder]  # raw folder components
    stems: list[str]
    tokens: list[list[str]]
    nxm: list[tuple[int, int] | None]

    @classmethod
    def from_paths(cls, paths: Sequence[str]) -> WalkFiles:
        folders, stems, tokens, nxm = [], [], [], []
        for path in paths:
            folder, file_name = N.split_path(path)
            stem = N.file_stem(file_name)
            folders.append(folder)
            stems.append(stem)
            tokens.append(N.tokenize(stem, split_glued=True))
            nxm.append(N.nxm_of(stem))
        return cls(folders, stems, tokens, nxm)


@dataclass
class WalkResult:
    """The walk's output, by file index (walk order)."""

    root: list[int]  # group representative per file
    sublabel: list[SubLabel | None]
    suggestions: list[tuple[int, int, str]]  # (file, file, reason) across different groups
    reasons: dict[int, Counter[str]]  # group representative -> join reasons
    folders: dict[Folder, FolderVerdict]
    decisions: dict[Folder, FolderDecision]
    effective: list[Folder]  # effective folder per file
    tree: EffectiveTree
    names: NameEvidence

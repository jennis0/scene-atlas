"""The effective folder tree (design/variant-grouping-algorithm.md §5).

Each raw folder is classified against its parent's and grandparent's names
(``names.folder_class``):

- **rendition** folders (grid / format / size / platform words, or the parent's name plus such
  words: ``Beast Prison 12x12`` under ``Beast Prison``, ``MA``, ``VTT``, ``70 DPI (VTT)``) and
  **variant** folders (``Night``, ``Winter``) are *transparent*: their files belong to the parent;
- **siblings** whose names are equal once rendition and axis words are dropped
  (``Forest Road Gridded`` / ``Forest Road Gridless``) collapse into one effective folder: they
  are renditions of one sub-group;
- **generic** (``Maps``, ``Pack 03``) and **specific** folders stay.

An effective folder is a tuple of canonical names (lower-case identity words, digits kept), so
mirror siblings collapse simply by producing the same tuple.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import names as N
from . import vocab as V
from .names import Folder, FolderClass

# A folder word within this similarity of a parent word is the parent's name misspelt
# (``colossas`` under ``Colossus``). Only words of >= 5 letters sharing their first two letters.
FUZZY_PARENT_RATIO = 0.8
FUZZY_MIN_LENGTH = 5

_TRANSPARENT = frozenset({FolderClass.RENDITION, FolderClass.VARIANT})


@dataclass
class EffectiveTree:
    """Raw folders mapped onto effective folders."""

    effective_of: dict[Folder, Folder]  # raw folder -> effective folder
    children: dict[Folder, set[Folder]] = field(default_factory=lambda: defaultdict(set))
    raw_names: dict[Folder, set[str]] = field(default_factory=lambda: defaultdict(set))
    """Effective folder -> raw names of the (non-transparent) folders that map onto it."""
    name_class: dict[Folder, FolderClass] = field(default_factory=dict)
    """Class of an effective folder's name: SPECIFIC if any raw folder mapping to it is specific."""

    def recurring_names(self) -> set[str]:
        """Names of effective folders with >= 2 children that occur at >= 2 places in the tree.

        Such a folder is an author or topic folder (``Forests/Moonlight Maps`` and
        ``Caves/Moonlight Maps``), not a location: a container.
        """
        places: dict[str, int] = defaultdict(int)
        for folder, kids in self.children.items():
            if folder and len(kids) >= 2:
                places[folder[-1]] += 1
        return {name for name, count in places.items() if count >= 2}


def _near_spellings(core: N.Seq, parent_tokens: set[str]) -> N.Seq:
    """Drop core tokens that are near-spellings of parent tokens (``colossas`` ~ ``colossus``)."""
    return tuple(
        t
        for t in core
        if not (
            len(t) >= FUZZY_MIN_LENGTH
            and any(
                len(p) >= FUZZY_MIN_LENGTH
                and p[:2] == t[:2]
                and difflib.SequenceMatcher(None, t, p).ratio() >= FUZZY_PARENT_RATIO
                for p in parent_tokens
            )
        )
    )


def _parent_tokens(raw: Folder) -> set[str]:
    """Identity tokens of a raw folder's parent and grandparent names."""
    out: set[str] = set()
    for name in raw[-3:-1]:
        out |= set(N.name_identity(name))
    return out


def _canonical_name(name: str, cls: FolderClass) -> str:
    """The effective name of a kept folder.

    A specific folder keeps its identity words and digits (``Dungeon Room 2`` and ``Dungeon
    Room 1`` stay apart) minus rendition and axis words, so mirror siblings coincide.
    """
    if cls is FolderClass.SPECIFIC:
        toks = [
            t
            for t in N.drop_grid_phrases(N.name_tokens(name))
            if t != V.DIMS and t not in V.STOPWORDS and t not in V.REND and t not in V.AXIS
        ]
        if toks:
            return " ".join(toks)
    return name.lower()


def _classify(raw: Folder) -> FolderClass:
    """Class of a raw folder's last component, given its ancestors."""
    parent_tokens = _parent_tokens(raw)
    cls, core = N.folder_class(raw[-1], parent_tokens)
    if cls is FolderClass.SPECIFIC and not _near_spellings(core, parent_tokens):
        return FolderClass.RENDITION  # its parent's name, misspelt, plus rendition words
    return cls


def build_tree(raw_folders: Iterable[Folder]) -> EffectiveTree:
    """The effective tree of the given raw folders (and all their ancestors)."""
    every: set[Folder] = {()}
    for raw in raw_folders:
        every.update(raw[:d] for d in range(1, len(raw) + 1))
    tree = EffectiveTree(effective_of={(): ()})
    tree.name_class[()] = FolderClass.GENERIC  # the root is never a map; see walk._container
    for raw in sorted(every, key=lambda r: (len(r), r)):
        if not raw:
            continue
        parent = tree.effective_of[raw[:-1]]
        cls = _classify(raw)
        if cls in _TRANSPARENT:
            tree.effective_of[raw] = parent
            continue
        eff = (*parent, _canonical_name(raw[-1], cls))
        tree.effective_of[raw] = eff
        tree.children[parent].add(eff)
        tree.raw_names[eff].add(raw[-1])
        if tree.name_class.get(eff) is not FolderClass.SPECIFIC:
            tree.name_class[eff] = cls
    return tree


def effective_folders(paths: Iterable[str]) -> dict[str, str]:
    """Each path's effective folder ("/"-joined canonical names, "" for the root).

    Rendition and variant folders are transparent, so ``X/Gridded/a.png`` and
    ``X/No Grid/b.png`` share ``X``'s, as do mirror siblings (``Forest Road Gridded`` /
    ``Forest Road Gridless``). A folder's effective name depends only on its own path, not on
    the other paths given. Ingest uses it to find a file's siblings before any grouping
    (``ingest_queue``: grid sizes named by sibling files).
    """
    ordered = list(dict.fromkeys(paths))
    folders = {path: N.split_path(path)[0] for path in ordered}
    tree = build_tree(folders.values())
    return {path: "/".join(tree.effective_of[folder]) for path, folder in folders.items()}


def ancestors(folder: str) -> list[str]:
    """A "/"-joined folder and its ancestors, nearest first, ending with the root ""."""
    parts = folder.split("/") if folder else []
    return ["/".join(parts[:k]) for k in range(len(parts), -1, -1)]

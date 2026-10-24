"""What each effective folder is, from the tree and the names alone.

These facts never change during the walk, so they are computed once, before it. The walk then
adds what depends on its units: the unit cap, the pack test and the content gates.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from . import names as N
from .names import Folder, FolderClass, NameEvidence
from .params import VARIANT_ONLY_SHARE
from .schema import FolderReason
from .tree import EffectiveTree
from .vocab import GENERIC


@dataclass(frozen=True)
class FolderFacts:
    """The name-based facts about one effective folder."""

    sealed_by: FolderReason | None  # a container by its name alone (root, generic, author, ...)
    named_after_files: bool  # its own name is its files' common name (>= 2 identity tokens)
    named_map: bool  # its files' common tokens are its map's name, carried by every keyed file
    house_gate: bool  # a4 / b4: its shared-base families are cohesion-gated (a house prefix)
    variant_only: bool  # a6: a named leaf folder of files without identity, so one map
    leaf: bool  # no child folders
    specific: bool  # its name class is specific (may name a map)

    @property
    def folder_named(self) -> bool:
        """Structural evidence that the folder is one map."""
        return self.named_after_files or self.named_map


def folder_facts(
    tree: EffectiveTree,
    names: NameEvidence,
    effective: Sequence[Folder],
    own: Mapping[Folder, Sequence[int]],
    subtree: Mapping[Folder, Sequence[int]],
    known_authors: Collection[str],
) -> dict[Folder, FolderFacts]:
    """Facts for every folder of ``subtree`` and ``tree.children``. ``own`` and ``subtree``
    map folders to file indices; ``known_authors`` are ``names.name_key``s of creators."""
    recurring = tree.recurring_names()
    out: dict[Folder, FolderFacts] = {}
    for P in set(subtree) | set(tree.children):
        files = own.get(P, ())
        leaf = not tree.children.get(P)
        specific = tree.name_class.get(P) is FolderClass.SPECIFIC
        info = names.folder_info.get(P)
        out[P] = FolderFacts(
            sealed_by=_sealed_by(P, tree, names, effective, subtree, recurring, known_authors),
            named_after_files=_named_after_files(P, names),
            named_map=_named_map(info, files, names),
            house_gate=bool(info and info.house) or _globally_housed(files, names),
            variant_only=leaf
            and specific
            and P[-1] not in recurring
            and _variant_only(P, files, names),
            leaf=leaf,
            specific=specific,
        )
    return out


def _sealed_by(
    P: Folder,
    tree: EffectiveTree,
    names: NameEvidence,
    effective: Sequence[Folder],
    subtree: Mapping[Folder, Sequence[int]],
    recurring: set[str],
    known_authors: Collection[str],
) -> FolderReason | None:
    """Why the folder is a container by what it is called, if it is: the root; a generic name;
    a name recurring elsewhere in the tree (an author or topic); a known author's name; or a
    house-prefix name spread over several of its folders."""
    if not P:
        return FolderReason.ROOT
    if tree.name_class.get(P) is FolderClass.GENERIC:
        return FolderReason.GENERIC
    if P[-1] in recurring:
        return FolderReason.RECURRING
    if known_authors and any(
        N.name_key(raw) in known_authors for raw in tree.raw_names.get(P, {P[-1]})
    ):
        return FolderReason.KNOWN_AUTHOR
    tokens = set(N.name_identity(P[-1]))
    if tokens and tokens <= names.global_house:
        # A house prefix is a convention across maps: the files carrying it must lie in >= 2
        # effective folders. A token confined to one folder is that folder's own name (a lone
        # map ``airships/`` imported alone, whose name the global strip reads as a prefix).
        homes = {effective[i] for i in subtree.get(P, ()) if names.stripped[i] & tokens}
        if len(homes) >= 2:
            return FolderReason.HOUSE_PREFIX
    return None


def _named_after_files(P: Folder, names: NameEvidence) -> bool:
    """The folder is named after its files' common name (>= 2 identity tokens shared)."""
    if not P:
        return False
    folder_tokens = set(N.name_identity(P[-1])) - GENERIC
    common = names.common_raw.get(P, set()) - GENERIC
    return len(folder_tokens & common) >= 2 and (folder_tokens <= common or common <= folder_tokens)


def _named_map(info: N.FolderNames | None, files: Sequence[int], names: NameEvidence) -> bool:
    """The folder's files' common tokens are its map's name (folder IDF), and every file with a
    name key carries them: a straggler with a name of its own is another map, so the common
    name would only be the majority map's."""
    if info is None or not info.named_map:
        return False
    common = set(info.common)
    return all(common <= names.unstripped(i) for i in files if names.veto_key[i] is not None)


def _variant_only(P: Folder, files: Sequence[int], names: NameEvidence) -> bool:
    """a6 for a specific, non-recurring leaf folder: most of its >= 2 files carry no identity
    (``Golden Forest/Night.webp``, ``Day.webp``), and its name is not a house prefix."""
    if not P or len(files) < 2 or set(N.name_identity(P[-1])) <= names.global_house:
        return False
    return sum(names.variant_only[i] for i in files) >= VARIANT_ONLY_SHARE * len(files)


def _globally_housed(files: Sequence[int], names: NameEvidence) -> bool:
    """The folder's files share a house prefix that the global strip removed, so folder IDF
    never saw it: the same gating verdict alone as inside a large import, where folder IDF
    finds the prefix."""
    named = [i for i in files if names.named[i] or names.stripped[i]]
    if len(named) < 3:
        return False
    housed = sum(bool(names.stripped[i] & names.global_house) for i in named)
    return housed >= N.COMMON_SHARE * len(named)

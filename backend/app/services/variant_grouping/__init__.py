"""Variant grouping v2: the bottom-up tree walk (design/variant-grouping.md, ADR-028).

Pure: no database, no filesystem, no model loading. Two entry points, one per pass:

- ``group_by_paths``: the seal pass, from paths alone (tree, names, folders, containers);
- ``group_with_content``: the refinement pass, adding pHash renditions, layout agreement and the
  cohesion-gated parent rules. Content only adds joins, so its groups are unions of the seal
  pass's groups (merge-only).

Both return a ``Grouping`` that is deterministic and independent of input order.

Modules: ``vocab`` (word lists), ``names`` (tokens, identity, folder IDF, hubs, levels),
``tree`` (effective tree), ``evidence`` (features, candidate pairs, pair signals), ``cohesion``
(unit gates), ``walk`` (the walk and ``GroupingParams``), ``naming`` (names and authors via
``ImageParser``), ``schema`` (inputs and outputs).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Hashable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from . import names as N
from .evidence import ContentFeatures, FeatureMatrix
from .naming import GroupNamer
from .schema import Grouping, GroupingFile, ProposedGroup, Suggestion
from .tree import build_tree
from .walk import EmbeddingThresholds, FolderDecision, GroupingParams, WalkFiles, run_walk

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser

__all__ = [
    "ContentFeatures",
    "EmbeddingThresholds",
    "FolderDecision",
    "Grouping",
    "GroupingFile",
    "GroupingParams",
    "ProposedGroup",
    "Suggestion",
    "group_by_paths",
    "group_with_content",
    "partition_keys",
]


def partition_keys(paths: Iterable[str]) -> dict[str, str]:
    """Each path's partition: the canonical name of its effective top-level folder, "" for
    files at the root.

    Rendition and variant folders are transparent, so ``Gridded/X/a.png`` and
    ``No Grid/X/a.png`` share the partition of ``X/a.png``, and mirror siblings
    (``Forest Road Gridded`` / ``Forest Road Gridless``) share one. The walk never joins
    files of different top-level folders from their paths (the root is always a container),
    so a seal group lies within one partition; only content (cross-tree renditions) joins
    across them. Ingest refines large imports partition by partition (ADR-028).
    """
    ordered = list(dict.fromkeys(paths))
    folders = {path: N.split_path(path)[0] for path in ordered}
    tree = build_tree(folders.values())
    keys: dict[str, str] = {}
    for path, folder in folders.items():
        effective = tree.effective_of[folder]
        keys[path] = effective[0] if effective else ""
    return keys


def group_by_paths[K: Hashable](
    files: Sequence[GroupingFile[K]],
    parser: ImageParser,
    params: GroupingParams | None = None,
    known_authors: Collection[str] = (),
) -> Grouping[K]:
    """Group files from their paths alone (the seal pass, design §3).

    Every join that needs content is withheld, never guessed, so ``group_with_content`` on the
    same files only merges these groups. ``known_authors`` are the creators already in the
    library: a folder named after one is the author, never a map.
    """
    return _group(files, None, params or GroupingParams(), parser, known_authors)


def group_with_content[K: Hashable](
    files: Sequence[GroupingFile[K]],
    features: Mapping[K, ContentFeatures],
    params: GroupingParams,
    parser: ImageParser,
    known_authors: Collection[str] = (),
) -> Grouping[K]:
    """Group files from their paths and content features (the refinement pass, design §3).

    Files missing from ``features``, or missing a feature, take part through names and folders
    only. ``params.embedding`` is the encoder's calibration; None switches embedding rules off.
    """
    return _group(files, features, params, parser, known_authors)


def _group[K: Hashable](
    files: Sequence[GroupingFile[K]],
    features: Mapping[K, ContentFeatures] | None,
    params: GroupingParams,
    parser: ImageParser,
    known_authors: Collection[str],
) -> Grouping[K]:
    ordered = sorted(files, key=lambda f: (f.path, str(f.key)))
    keys = [f.key for f in ordered]
    if len(set(keys)) != len(keys):
        raise ValueError("grouping file keys must be unique")
    if not ordered:
        return Grouping(groups=[])
    paths = [f.path for f in ordered]
    walk_files = WalkFiles.from_paths(paths)
    matrix = None
    if features:
        matrix = FeatureMatrix(
            [features.get(k) for k in keys], use_embeddings=params.embedding is not None
        )
    result = run_walk(walk_files, matrix, params)

    members: dict[int, list[int]] = defaultdict(list)
    for i, root in enumerate(result.root):
        members[root].append(i)  # walk order is path order, so groups come out sorted
    namer = GroupNamer(parser, result, walk_files, paths, known_authors)
    groups: list[ProposedGroup[K]] = []
    group_of: dict[int, int] = {}
    for root, idx in members.items():
        named = namer.name(idx)
        subgroups = {
            keys[i]: namer.subgroup_label(label)
            for i in idx
            if (label := result.sublabel[i]) is not None
        }
        group_of[root] = len(groups)
        groups.append(
            ProposedGroup(
                keys=[keys[i] for i in idx],
                name=named.name,
                author=named.author,
                name_is_identity=named.is_identity,
                subgroups=subgroups,
                reasons=result.reasons.get(root, Counter()),
            )
        )

    suggestions: list[Suggestion] = []
    seen: set[tuple[int, int]] = set()
    for x, y, reason in result.suggestions:
        a, b = sorted((group_of[result.root[x]], group_of[result.root[y]]))
        if a != b and (a, b) not in seen:
            seen.add((a, b))
            suggestions.append(Suggestion(a, b, reason))
    decisions = {"/".join(folder): d for folder, d in result.decisions.items()}
    return Grouping(groups=groups, suggestions=suggestions, decisions=decisions)

"""Variant grouping v2: the bottom-up tree walk (design/variant-grouping.md, ADR-028).

Pure: no database, no filesystem, no model loading. Entry points:

- ``group_with_content``: what an import's grouping phase runs once it has finished
  (``backend/pipeline/group_jobs.py``): paths plus pHash renditions, layout agreement and the
  cohesion-gated parent rules;
- ``group_by_paths``: from paths alone (tree, names, folders, containers), every content join
  withheld. Content only adds joins, so ``group_with_content``'s groups are unions of these
  (tested; the research parity bench measures both);
- ``effective_folders``: each file's effective folder (ingest finds a file's siblings by it).

The groupings are deterministic and independent of input order.

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
from .walk import (
    EmbeddingThresholds,
    FolderDecision,
    GroupingParams,
    WalkFiles,
    author_key,
    run_walk,
)

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
    "effective_folders",
    "group_with_content",
]


def effective_folders(paths: Iterable[str]) -> dict[str, str]:
    """Each path's effective folder ("/"-joined canonical names, "" for the root).

    Rendition and variant folders are transparent, so ``X/Gridded/a.png`` and
    ``X/No Grid/b.png`` share ``X``'s, as do mirror siblings (``Forest Road Gridded`` /
    ``Forest Road Gridless``). A folder's effective name depends only on its own path, not on
    the other paths given. Ingest uses it to find a file's siblings at seal, before any
    grouping (``ingest_queue``: grid sizes named by sibling files).
    """
    ordered = list(dict.fromkeys(paths))
    folders = {path: N.split_path(path)[0] for path in ordered}
    tree = build_tree(folders.values())
    return {path: "/".join(tree.effective_of[folder]) for path, folder in folders.items()}


def group_by_paths[K: Hashable](
    files: Sequence[GroupingFile[K]],
    parser: ImageParser,
    params: GroupingParams | None = None,
    known_authors: Collection[str] = (),
) -> Grouping[K]:
    """Group files from their paths alone (no content evidence).

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
    """Group files from their paths and content features (an import's grouping, design §3).

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
    # A folder named after a known creator, as written or as the parser cleans it, is an author
    authors = frozenset(
        key
        for author in known_authors
        for key in (author_key(author), author_key(parser.clean_group_name(author)))
        if key
    )
    result = run_walk(walk_files, matrix, params, authors)

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

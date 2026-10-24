"""Variant grouping: the bottom-up tree walk (design/variant-grouping.md, ADR-028).

Pure: no database, no filesystem, no model loading. Entry points:

- ``group_with_content``: what an import's grouping phase runs once it has finished
  (``backend/pipeline/group_jobs.py``): paths plus pHash renditions, layout agreement and the
  cohesion-gated parent rules. Without features (``{}``) it groups by paths alone, every content
  join withheld; content only adds joins, so groups with content are unions of those;
- ``group_scenes``: an import's scenes, attached to the map groups or grouped among themselves,
  after the maps were grouped alone;
- ``effective_folders``: each file's effective folder (ingest finds a file's siblings by it).

The groupings are deterministic and independent of input order.

Modules, in dependency order: ``vocab`` (word lists), ``names`` (tokens, identity, folder IDF,
hubs, levels), ``tree`` (effective tree), ``params`` (thresholds), ``schema`` (inputs, outputs
and folder verdicts), ``phash_index`` and ``evidence`` (features, candidate pairs, pair signals),
``cohesion`` (unit gates), ``folders`` (what each folder is, from names), ``walk`` (the walk),
``naming`` (names and authors via ``ImageParser``), ``scenes`` (scenes).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Hashable, Mapping, Sequence
from typing import TYPE_CHECKING

from . import names as N
from .evidence import ContentFeatures, FeatureMatrix
from .naming import GroupNamer
from .params import EmbeddingThresholds, GroupingParams
from .scenes import SceneAttachment, SceneGrouping, group_scenes
from .schema import (
    FolderDecision,
    FolderReason,
    FolderVerdict,
    Grouping,
    GroupingFile,
    ProposedGroup,
    Suggestion,
    WalkFiles,
)
from .tree import effective_folders
from .walk import run_walk

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser

__all__ = [
    "ContentFeatures",
    "EmbeddingThresholds",
    "FolderDecision",
    "FolderReason",
    "FolderVerdict",
    "Grouping",
    "GroupingFile",
    "GroupingParams",
    "ProposedGroup",
    "SceneAttachment",
    "SceneGrouping",
    "Suggestion",
    "effective_folders",
    "group_scenes",
    "group_with_content",
]


def group_with_content[K: Hashable](
    files: Sequence[GroupingFile[K]],
    features: Mapping[K, ContentFeatures],
    params: GroupingParams,
    parser: ImageParser,
    known_authors: Collection[str] = (),
) -> Grouping[K]:
    """Group files from their paths and content features (an import's grouping).

    Files missing from ``features``, or missing a feature, take part through names and folders
    only; with no features at all the grouping is by paths alone. ``params.embedding`` is the
    encoder's calibration; None switches embedding rules off. ``known_authors`` are the
    creators already in the library: a folder named after one is the author, never a map.
    """
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
    known = _known_authors(known_authors, parser)
    result = run_walk(walk_files, matrix, params, frozenset(known))

    members: dict[int, list[int]] = defaultdict(list)
    for i, root in enumerate(result.root):
        members[root].append(i)  # walk order is path order, so groups come out sorted
    namer = GroupNamer(parser, result, walk_files, paths, known)
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
    return Grouping(groups, suggestions, folders=result.folders, decisions=decisions)


def _known_authors(known_authors: Collection[str], parser: ImageParser) -> dict[str, str]:
    """Creators by ``names.name_key``, as written and as the parser cleans them (ties: the
    smallest name)."""
    known: dict[str, str] = {}
    for author in sorted(known_authors):
        for key in (N.name_key(author), N.name_key(parser.clean_group_name(author))):
            if key:
                known.setdefault(key, author)
    return known

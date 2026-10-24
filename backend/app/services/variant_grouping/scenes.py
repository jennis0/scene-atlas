"""Scenes in an import's grouping (design/variant-grouping-algorithm.md §7b).

Maps are grouped by the walk alone, so adding scenes never changes the map groups. Scenes then:

1. **Attach** to a map group, by folder or name only (a scene and a map of one place share no
   content: their pHashes are as far apart as unrelated pictures'):
   - ``r2``: the nearest folder holding maps holds one map group, and is either the scene's own
     folder with maps directly in it, or not a container and that group's own top folder. So a
     folder of one map and its scenes is one group, but a scene does not join a map elsewhere under
     the import root, an author or a pack;
   - ``r3``: in a folder holding several map groups, a scene whose name key (variant, rendition and
     role words stripped) starts with exactly one group's key joins it (neighbours only).

   Role folders (``Scenes``, ``Art``, ``Assets & Tokens``) and ``Maps`` folders are transparent here,
   so ``Loc/Scenes/x.jpg`` is one of ``Loc``'s files and ``Pack/Maps/X`` mirrors ``Pack/Scenes/X``.
2. **Group** the rest (``r5``), per folder: every scene starts alone and joins only on positive
   evidence: an identical, leading name key (numbers alone never count), a variant-only place
   folder (``Golden Forest/Night.jpg``), a pHash rendition, or layout and embedding agreement at the
   scene calibration. Across folders (``r6``) only certain renditions join.

A unit holding one map group never joins a unit holding another. Pure and deterministic: files are
processed in ``(path, str(key))`` order, as the walk.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from . import names as N
from . import vocab as V
from .evidence import ContentFeatures, FeatureMatrix
from .params import VARIANT_ONLY_SHARE, GroupingParams
from .phash_index import radius_pairs
from .schema import FolderVerdict, Grouping, GroupingFile
from .tree import ancestors, build_tree
from .walk import UnionFind, join_agreeing

_INTERIOR_EXTERIOR = frozenset({"interior", "exterior"})
_HEX_ID = re.compile(r"[0-9a-f]{6,}([-_][0-9a-f]{3,})+|[0-9a-f]{16,}")
_MIXED_ID = re.compile(r"(?=[a-z]*\d)(?=\d*[a-z])[a-z0-9]{5,12}")
# Row blocks for the dense agreement search (bounded memory on very large folders)
_AGREE_BLOCK = 512


@dataclass(frozen=True)
class SceneAttachment:
    """A scene that joins a map group: the group's index in the map ``Grouping`` and why."""

    group: int
    reason: str  # "r2 folder holds one map group", "r3 name key (prefix)", or the first r5 / r6
    # join that brought it to a scene group holding an attached scene


@dataclass
class SceneGrouping[K: Hashable]:
    """Scenes attached to map groups, and the groups of the others (singletons included)."""

    attachments: dict[K, SceneAttachment] = field(default_factory=dict)
    groups: list[list[K]] = field(default_factory=list)  # in path order
    joins: list[tuple[K, K, str]] = field(default_factory=list)  # every join made, in order

    def debug_lines(self) -> list[str]:
        """One line per join (attachments to map groups included), for DEBUG logging."""
        return [f"scene: {a!r} + {b!r} ({reason})" for a, b, reason in self.joins]


# ---------------------------------------------------------------------------- names


def scene_identity(stem: str) -> N.Seq:
    """A scene's name key: identity tokens minus role words (and the phrase "Interior Scene")."""
    toks = N.tokenize(stem, split_glued=True)
    toks = [
        t
        for k, t in enumerate(toks)
        if not (
            t in _INTERIOR_EXTERIOR and k + 1 < len(toks) and toks[k + 1] in ("scene", "scenes")
        )
    ]
    return tuple(
        t
        for t in N.identity_tokens(toks)
        if t not in V.ROLE_WORDS and t not in V.SCENE_AXIS and t not in V.COUNTER_WORDS
    )


def _map_identity(stem: str) -> N.Seq:
    return N.strip_level_suffix(scene_identity(stem))


def _key_leads(stem: str, key: N.Seq, strip: set[str]) -> bool:
    """The key's tokens come first in the name, before any variant word: "Tavern Night" leads
    with "tavern"; "foggy_dark_village" does not lead with "village"."""
    toks: list[str] = []
    for t in N.tokenize(stem, split_glued=True):
        if (
            t.isdigit()
            or t in V.STOPWORDS
            or len(t) <= 1
            or t in V.ROLE_WORDS
            or t in strip
            or t in V.REND
            or t == V.DIMS
        ):
            continue
        if t not in toks:
            toks.append(t)
    return tuple(toks[: len(key)]) == key


def _variant_only(stem: str) -> bool:
    """Named only by variant words, at least one (``Night``, ``Day 2``, ``Default``)."""
    words = [
        t for t in N.tokenize(stem, split_glued=True) if not t.isdigit() and t not in V.STOPWORDS
    ]
    variant = V.AXIS | V.SCENE_AXIS
    return (
        bool(words)
        and all(t in variant or t in V.REND for t in words)
        and any(t in variant for t in words)
    )


def _id_like(stem: str) -> bool:
    """An identifier, not a name: a UUID or hex run, or a short letters-and-digits token
    (``d83lgl``). Its letter fragments carry no identity."""
    text = stem.lower().strip()
    return bool(_HEX_ID.fullmatch(text) or _MIXED_ID.fullmatch(text))


def _numbering_norm(stem: str) -> tuple[str, ...]:
    """What is left of a name without numbers and rendition words."""
    return tuple(
        w
        for w in N.tokenize(stem, split_glued=True)
        if not w.isdigit() and w not in V.REND and w != V.DIMS
    )


def _numbered_siblings(a: str, b: str) -> bool:
    """Different stems that differ only by a number or rendition words (``x-04`` / ``x-12`` /
    ``x-scaled``): a numbering, not a variant."""
    return a.lower() != b.lower() and _numbering_norm(a) == _numbering_norm(b)


def _numbered_collection(stems: list[str]) -> bool:
    """A name family of >= 3 that is mostly numbered siblings (``the-art-of-x-07``, ``-16``): the
    shared key is a collection's (an artist's, an article's), not a place's."""
    if len(stems) < 3:
        return False
    norms = [_numbering_norm(t) for t in stems]
    with_sibling = sum(
        any(
            i != j and norms[i] == norms[j] and stems[i].lower() != stems[j].lower()
            for j in range(len(stems))
        )
        for i in range(len(stems))
    )
    return with_sibling >= 0.5 * len(stems)


def _folder_words(name: str) -> list[str]:
    return [
        t for t in N.name_tokens(name) if not t.isdigit() and t not in V.STOPWORDS and len(t) > 1
    ]


def is_role_folder(name: str) -> bool:
    """A folder named only by role words (``Scenes``, ``Concept Art``, ``Assets & Tokens``)."""
    words = _folder_words(name)
    return bool(words) and all(t in V.ROLE_WORDS or t in V.ROLE_FOLDER_EXTRA for t in words)


def _is_maps_folder(name: str) -> bool:
    """A folder that only says it holds maps (``Maps``, ``Battle Maps``)."""
    words = _folder_words(name)
    return bool(words) and all(t in V.MAPS_FOLDER_WORDS for t in words)


def _common_strip(keys: list[N.Seq]) -> set[str]:
    """Tokens in >= ``COMMON_SHARE`` of >= 3 named keys (a house prefix such as ``tc``), stripped
    only when >= 2 distinct non-empty names remain without them."""
    named = [k for k in keys if k]
    if len(named) < 3:
        return set()
    common = N.common_tokens(named)
    if not common:
        return set()
    residuals = {tuple(t for t in k if t not in common) for k in named}
    residuals.discard(())
    return common if len(residuals) >= 2 else set()


# ---------------------------------------------------------------------------- folders


def _attach_folder(raw: N.Folder) -> N.Folder:
    """A file's folder with role folders and ``Maps`` folders dropped."""
    return tuple(c for c in raw if not is_role_folder(c) and not _is_maps_folder(c))


def _effective(folders: Sequence[N.Folder]) -> dict[N.Folder, N.Folder]:
    """Each folder's effective folder."""
    tree = build_tree(folders)
    return {f: tree.effective_of[f] for f in folders}


def _top(folders: list[str]) -> str:
    """The longest common folder of "/"-joined ``folders``."""
    return "/".join(N.common_prefix(f.split("/") if f else () for f in folders))


# ---------------------------------------------------------------------------- units


class _Units(UnionFind):
    """Union-find over files; a unit holding a map group never joins one holding another."""

    def __init__(self, n: int):
        super().__init__(n)
        self.map_group: list[int | None] = [None] * n

    def union(self, a: int, b: int) -> bool:
        ga, gb = self.map_group[self.find(a)], self.map_group[self.find(b)]
        if ga is not None and gb is not None and ga != gb:
            return False
        if not super().union(a, b):
            return False
        self.map_group[self.find(a)] = ga if ga is not None else gb
        return True


def _renditions(fm: FeatureMatrix, params: GroupingParams) -> list[tuple[int, int]]:
    """Pairs (a < b) of ``fm``'s rows that are certain renditions (pHash within
    ``rendition_bits``, the same aspect), sorted."""
    idx = np.flatnonzero(fm.has_phash & fm.has_aspect)
    local = radius_pairs(fm.phash[idx], params.rendition_bits)
    a, b = idx[local[:, 0]], idx[local[:, 1]]
    close = np.abs(fm.log_aspect[a] - fm.log_aspect[b]) < params.rendition_aspect
    return list(zip(a[close].tolist(), b[close].tolist(), strict=True))


# ---------------------------------------------------------------------------- grouping


def group_scenes[K: Hashable](
    map_grouping: Grouping[K] | None,
    map_files: Sequence[GroupingFile[K]],
    scene_files: Sequence[GroupingFile[K]],
    features: Mapping[K, ContentFeatures],
    params: GroupingParams,
) -> SceneGrouping[K]:
    """Attach scenes to the map walk's groups and group the rest (see the module docstring).

    ``map_grouping`` is ``group_with_content`` on ``map_files`` (None when there are no maps).
    ``features`` are the scenes' (any maps' are ignored). Embedding agreement needs
    ``params.embedding`` (the encoder's calibration); without it, names, folders and renditions
    still work.
    """
    out: SceneGrouping[K] = SceneGrouping()
    files = sorted(
        [(f.key, f.path, True) for f in map_files] + [(f.key, f.path, False) for f in scene_files],
        key=lambda t: (t[1], str(t[0])),
    )
    keys = [f[0] for f in files]
    n = len(files)
    index = {k: i for i, k in enumerate(keys)}
    maps = [i for i in range(n) if files[i][2]]
    scenes = [i for i in range(n) if not files[i][2]]
    groups = [[index[k] for k in g.keys] for g in map_grouping.groups] if map_grouping else []
    verdicts = map_grouping.folders if map_grouping else {}
    group_of = {i: g for g, members in enumerate(groups) for i in members}
    if not scenes:
        return out

    p = params
    split = [N.split_path(f[1]) for f in files]
    raw = [folder for folder, _ in split]
    stem = [N.file_stem(name) for _, name in split]
    attach_of = _effective([_attach_folder(f) for f in raw])
    folder = ["/".join(attach_of[_attach_folder(f)]) for f in raw]
    container = _container_verdict(raw, maps, verdicts)

    under, nearest = _map_groups_above(maps, scenes, folder, group_of)
    scene_ids = {s: scene_identity(stem[s]) for s in scenes}
    attach = _attach_by_folder(scenes, maps, folder, groups, under, nearest, container)
    attach.update(
        _attach_by_name(scenes, maps, folder, stem, scene_ids, groups, under, nearest, attach)
    )

    units = _Units(n)
    for s, (g, _) in attach.items():
        units.map_group[s] = g
    for i in maps:
        units.map_group[i] = group_of[i]
    for members in groups:
        for i in members[1:]:
            units.union(members[0], i)
    for s, (g, reason) in attach.items():
        units.union(groups[g][0], s)
        out.joins.append((keys[s], keys[groups[g][0]], reason))

    def join(a: int, b: int, reason: str) -> None:
        if units.union(a, b):
            out.joins.append((keys[a], keys[b], reason))

    # Content of scenes only, by position in ``scenes``; renditions within and across folders
    fm = FeatureMatrix(
        [features.get(keys[s]) for s in scenes], use_embeddings=p.embedding is not None
    )
    within: dict[str, list[tuple[int, int]]] = defaultdict(list)
    across: list[tuple[int, int]] = []
    for x, y in _renditions(fm, p):
        a, b = scenes[x], scenes[y]
        (within[folder[a]] if folder[a] == folder[b] else across).append((a, b))

    # r5: within each scene folder, alone unless there is positive evidence
    leaves: dict[str, list[int]] = defaultdict(list)
    for s in scenes:
        leaves[folder[s]].append(s)
    row = {s: r for r, s in enumerate(scenes)}
    for leaf, scoped in leaves.items():
        if len(scoped) >= 2:
            _leaf_joins(leaf, scoped, stem, scene_ids, within[leaf], fm, row, p, units, join)

    # r6: across folders, certain renditions only
    for a, b in across:
        ra, rb = units.find(a), units.find(b)
        if ra == rb or min(units.size[ra], units.size[rb]) >= p.big_join:
            continue
        join(a, b, "r6 rendition across folders")

    _collect(out, keys, scenes, units, attach)
    return out


def _map_groups_above(
    maps: list[int], scenes: list[int], folder: list[str], group_of: Mapping[int, int]
) -> tuple[dict[str, set[int]], dict[int, str | None]]:
    """The map groups under each folder holding maps, and each scene's nearest such folder."""
    under: dict[str, set[int]] = defaultdict(set)
    for i in maps:
        for a in ancestors(folder[i]):
            under[a].add(group_of[i])
    nearest = {s: next((a for a in ancestors(folder[s]) if a in under), None) for s in scenes}
    return under, nearest


def _collect[K: Hashable](
    out: SceneGrouping[K],
    keys: list[K],
    scenes: list[int],
    units: _Units,
    attach: Mapping[int, tuple[int, str]],
) -> None:
    """Fill ``out`` from the units: each scene's attachment (the reason it attached, or the first
    join that brought it to an attached unit), or its scene group."""
    first_join: dict[K, str] = {}
    for a, b, reason in out.joins:
        first_join.setdefault(a, reason)
        first_join.setdefault(b, reason)
    rest: dict[int, list[K]] = defaultdict(list)
    for s in scenes:
        g = units.map_group[units.find(s)]
        if g is not None:
            reason = attach[s][1] if s in attach else first_join.get(keys[s], "r5")
            out.attachments[keys[s]] = SceneAttachment(g, reason)
        else:
            rest[units.find(s)].append(keys[s])
    out.groups = list(rest.values())


def _container_verdict(
    raw: list[N.Folder], maps: list[int], verdicts: Mapping[N.Folder, FolderVerdict]
) -> Callable[[str], bool]:
    """The walk's container verdict per attach folder: that of the shallowest raw map folder
    standing for it (``Pack`` for ``Pack``, not the generic ``Pack/Maps``)."""
    prefixes = sorted(
        {raw[i][:d] for i in maps for d in range(len(raw[i]) + 1)}, key=lambda f: (len(f), f)
    )
    attach_eff = _effective([_attach_folder(f) for f in prefixes])
    walk_eff = _effective(prefixes)
    walk_of: dict[str, N.Folder] = {}
    for f in prefixes:
        walk_of.setdefault("/".join(attach_eff[_attach_folder(f)]), walk_eff[f])

    def container(a: str) -> bool:
        verdict = verdicts.get(walk_of[a]) if a in walk_of else None
        return True if verdict is None else verdict.container

    return container


def _attach_by_folder(
    scenes: list[int],
    maps: list[int],
    folder: list[str],
    groups: list[list[int]],
    under: Mapping[str, set[int]],
    nearest: Mapping[int, str | None],
    container: Callable[[str], bool],
) -> dict[int, tuple[int, str]]:
    """r2: the nearest folder holding maps holds one group (guarded: own folder, or the group's
    top)."""
    direct = {folder[i] for i in maps}
    top = {g: _top([folder[i] for i in members]) for g, members in enumerate(groups)}
    attach: dict[int, tuple[int, str]] = {}
    for s in scenes:
        a = nearest[s]
        if a is None or len(under[a]) != 1:
            continue
        (g,) = under[a]
        if (a == folder[s] and a in direct) or (not container(a) and a == top[g]):
            attach[s] = (g, "r2 folder holds one map group")
    return attach


def _attach_by_name(
    scenes: list[int],
    maps: list[int],
    folder: list[str],
    stem: list[str],
    scene_ids: Mapping[int, N.Seq],
    groups: list[list[int]],
    under: Mapping[str, set[int]],
    nearest: Mapping[int, str | None],
    attached: Mapping[int, tuple[int, str]],
) -> dict[int, tuple[int, str]]:
    """r3: in its own folder of several map groups, a scene's name key starts with one group's
    key. Scenes in ``attached`` are skipped."""
    map_ids = {i: _map_identity(stem[i]) for i in maps}
    scope: dict[str, list[int]] = defaultdict(list)
    for s in scenes:
        a = nearest[s]
        if s not in attached and a is not None and len(under[a]) >= 2 and folder[s] == a:
            scope[a].append(s)
    attach: dict[int, tuple[int, str]] = {}
    for a, scoped in scope.items():
        candidates = sorted(under[a])
        members = {g: [i for i in groups[g] if a in ancestors(folder[i])] for g in candidates}
        strip = _common_strip(
            [map_ids[i] for g in candidates for i in members[g]] + [scene_ids[s] for s in scoped]
        )
        group_keys: dict[int, set[N.Seq]] = {}
        for g in candidates:
            ids = [
                x for x in (tuple(t for t in map_ids[i] if t not in strip) for i in members[g]) if x
            ]
            if not ids:
                continue
            prefix = N.common_prefix(ids)
            group_keys[g] = {prefix} if prefix else {x[:2] for x in ids if len(x) >= 2}
        for s in scoped:
            key = tuple(t for t in scene_ids[s] if t not in strip)
            best = _leading_group(key, group_keys) if key else None
            if best is not None:
                attach[s] = (best, "r3 name key (prefix)")
    return attach


def _leading_group(key: N.Seq, group_keys: Mapping[int, set[N.Seq]]) -> int | None:
    """The group whose longest key ``key`` equals or starts with (keys of two tokens or more for a
    prefix); None when no group's does, or two groups' tie."""
    best, best_len, tie = None, 0, False
    for g, gkeys in group_keys.items():
        for k in gkeys:
            if key == k or (len(k) >= 2 and key[: len(k)] == k):
                if len(k) > best_len:
                    best, best_len, tie = g, len(k), False
                elif len(k) == best_len and g != best:
                    tie = True
    return None if tie else best


def _leaf_joins(
    leaf: str,
    scoped: list[int],
    stem: list[str],
    scene_ids: Mapping[int, N.Seq],
    renditions: list[tuple[int, int]],
    fm: FeatureMatrix,
    row: Mapping[int, int],
    p: GroupingParams,
    units: _Units,
    join: Callable[[int, int, str], None],
) -> None:
    """r5 in one folder's scenes: names, a variant-only place folder, renditions, agreement.
    ``fm`` holds the scenes' features at rows ``row[s]``."""
    strip = _common_strip([scene_ids[s] for s in scoped])
    key = {s: tuple(t for t in scene_ids[s] if t not in strip) for s in scoped}
    key2 = {s: (key[s][:2] if len(key[s]) >= 2 else None) for s in scoped}

    # Names: identical, leading keys with a real word, and stems that differ by more than a number
    families: dict[N.Seq, list[int]] = defaultdict(list)
    for s in scoped:
        if not _id_like(stem[s]) and key[s] and _key_leads(stem[s], key[s], strip):
            families[key[s]].append(s)
    for k, members in families.items():
        if not any(sum(ch.isalpha() for ch in t) >= 3 for t in k):
            continue
        if _numbered_collection([stem[x] for x in members]):
            continue
        for s in members:
            for t in members:
                if t == s or stem[t].lower() == stem[s].lower():
                    continue
                if not _numbered_siblings(stem[t], stem[s]):
                    join(t, s, "r5 same name key (identical)")
                    break

    # A specific place folder of scenes named only by variant words is one place
    if leaf:
        last = leaf.split("/")[-1]
        if not is_role_folder(last) and N.folder_class(last, set())[0] is N.FolderClass.SPECIFIC:
            variant_only = [s for s in scoped if _variant_only(stem[s])]
            if len(variant_only) >= 2 and len(variant_only) >= VARIANT_ONLY_SHARE * len(scoped):
                for s in scoped[1:]:
                    join(scoped[0], s, "r5 variant-only place folder")

    for a, b in renditions:
        join(a, b, "r5 rendition")

    if p.embedding is None:
        return
    ok = [
        s
        for s in scoped
        if fm.has_edge[row[s]] and fm.has_embedding[row[s]] and fm.has_aspect[row[s]]
    ]
    if len(ok) < 2:
        return
    rows = [row[s] for s in ok]
    emb, edge, aspect = fm.embedding[rows], fm.edge[rows], fm.log_aspect[rows]
    threshold = p.embedding.scene_agree

    def agreeing():
        for start in range(0, len(ok), _AGREE_BLOCK):
            cosine = emb[start : start + _AGREE_BLOCK] @ emb.T
            for r, c in np.argwhere(cosine >= threshold):
                x, y = ok[start + r], ok[c]
                if x >= y or abs(aspect[start + r] - aspect[c]) >= p.agree_aspect:
                    continue
                if float(edge[start + r] @ edge[c]) < p.scene_agree_edge:
                    continue
                if key2[x] and key2[y] and key2[x] != key2[y]:
                    continue
                yield x, y

    join_agreeing(
        units,
        agreeing(),
        p.agree_fraction,
        lambda x, y: join(x, y, "r5 same layout (scene calibration)"),
    )

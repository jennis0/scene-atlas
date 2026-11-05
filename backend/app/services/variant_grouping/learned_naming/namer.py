"""Names the groups of one walk: import-wide statistics, then per group the candidates, their
features and the models' picks."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from .. import names as N
from .. import vocab as V
from ..names import Folder, FolderClass
from ..schema import FolderReason, WalkFiles, WalkResult
from .author_features import (
    ACand,
    author_candidates,
    author_features,
    is_category_folder,
    is_frag_word,
    is_library_folder,
)
from .name_features import Cands, name_candidates, name_features
from .text import Cleaner, author_key, by_split, runs, sample, shown_author

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser

    from ..naming import GroupName
    from . import LearnedNamer

PAIR_K = 8  # candidates re-ranked pairwise
AUTHOR_THRESHOLD = 0.05
LIBRARY_TOPS = 2  # top-level folders credited over the whole import that make it a library
REASONS = list(FolderReason)


@dataclass
class Group:
    """The group being named, and the rules' choices for it."""

    index: int
    members: Sequence[int]
    sample: list[int]  # members read for stem candidates
    common_eff: Folder  # the members' common effective folder
    rule: GroupName
    naming_folder: Folder | None
    folders: dict[Folder, dict] = field(init=False)  # raw prefix -> ``_folder_info``


@dataclass(frozen=True)
class Request:
    """A group to name, and the rules' choices for it."""

    members: Sequence[int]
    rule: GroupName
    naming_folder: Folder | None
    identity_name: str | None
    folder_name: str | None


class Stats:
    """Token and folder statistics over a set of the walk's groups: the whole import, or one
    top-level folder of a library of several (see ``WalkNamer._authors``)."""

    def __init__(
        self,
        size: int,
        folder_groups: Mapping[Folder, set[int]],
        within: set[int] | None = None,
    ):
        self.size = size  # groups in the set
        self.n_others = max(1, size - 1)
        self.gdf: Counter[str] = Counter()  # per token, the groups whose paths hold it
        self.run_groups: dict[tuple[str, ...], set[int]] = defaultdict(set)
        self._folder_groups = folder_groups
        self._within = within  # None: every group

    def add(self, g: int, tokens: set[str], group_runs: set[tuple[str, ...]]) -> None:
        self.gdf.update(tokens)
        for run in group_runs:
            self.run_groups[run].add(g)

    def group_share(self, token: str) -> float:
        """Share of the set's other groups whose paths hold a token."""
        return (self.gdf.get(token, 1) - 1) / self.n_others

    def holders(self, grp: Group, run: tuple[str, ...]) -> set[int]:
        """The groups whose paths hold a token run, this one included."""
        return self.run_groups.get(run, set()) | {grp.index}

    def scope(self, grp: Group) -> set[int]:
        """Groups under the group's effective folder; when it holds only this group, under the
        nearest enclosing folder holding others (never beyond the set)."""
        folder = grp.common_eff
        while True:
            groups = self._folder_groups.get(folder, {grp.index})
            if self._within is not None:
                groups = groups & self._within
            if len(groups) >= 2 or not folder:
                return groups
            folder = folder[:-1]


def _below(c: ACand | None, top: Folder) -> bool:
    """Whether an author candidate is a folder below ``top``."""
    return c is not None and c.folder is not None and c.folder["depth"] >= len(top)


class WalkNamer:
    """Names the groups of one walk; import-wide statistics are computed once.

    ``known_author`` maps a folder name to the known author it names; ``authors`` maps
    ``author_key``s to known authors' display names, which replace a predicted author's text.

    Names are scored with statistics over the whole import; authors, in a library of several
    makers' folders, over the group's top-level folder (``_authors``)."""

    def __init__(
        self,
        model: LearnedNamer,
        parser: ImageParser,
        result: WalkResult,
        files: WalkFiles,
        known_author: Callable[[str], str | None],
        authors: Mapping[str, str],
    ):
        self._m = model
        self.tables = model.tables
        self._clean = Cleaner(parser, model.tables)
        self.res = result
        self.files = files
        self._known_author = known_author
        self.authors = authors
        by_root: dict[int, list[int]] = defaultdict(list)
        for i, root in enumerate(result.root):
            by_root[root].append(i)
        self.groups = list(by_root.values())
        self._group_of = {}
        for g, members in enumerate(self.groups):
            for i in members:
                self._group_of[i] = g
        self.folder_groups: dict[Folder, set[int]] = defaultdict(set)
        for i, eff in enumerate(result.effective):
            for d in range(len(eff) + 1):
                self.folder_groups[eff[:d]].add(self._group_of[i])
        self.by_author = [parser.author_from_stem(s) for s in files.stems]
        self.split_stems = [
            by_split(s, a) for s, a in zip(files.stems, self.by_author, strict=True)
        ]
        self.clean_name = lru_cache(maxsize=None)(parser.clean_group_name)
        self.stats = Stats(len(self.groups), self.folder_groups)
        self.tops = self._tops()
        by_top: dict[Folder, set[int]] = defaultdict(set)
        for g, top in enumerate(self.tops):
            if top is not None:
                by_top[top].add(g)
        self.top_stats = {t: Stats(len(gs), self.folder_groups, gs) for t, gs in by_top.items()}
        self._index_tokens()

    def _tops(self) -> list[Folder | None]:
        """Per group, its top-level folder, or None (it spans several, or is at the root).

        Top-level folders are the first level where the import's files part ways, below any
        folder that every file shares and that cannot be an author (``Battle Maps/``, a
        rendition folder). A folder named by one content word ("Forests") is a category, not a
        maker's folder: its groups get None. An import with fewer than two has none."""
        folders = self.files.folders
        first = folders[0] if folders else ()
        d = 0
        while (
            d < len(first)
            and all(len(f) > d and f[d] == first[d] for f in folders)
            and (N.is_rendition_folder_name(first[d]) or is_library_folder(self, first[d]))
        ):
            d += 1
        tops: list[Folder | None] = []
        for members in self.groups:
            at = {folders[i][: d + 1] if len(folders[i]) > d else None for i in members}
            top = at.pop() if len(at) == 1 else None
            tops.append(None if top is None or is_category_folder(self, top[-1]) else top)
        if len({t for t in tops if t is not None}) < 2:
            return [None] * len(tops)
        return tops

    def _index_tokens(self) -> None:
        """Per group its stem tokens; for the import and for each group's author statistics,
        per token the groups whose paths hold it and per token run the groups whose stems or
        folder names hold it."""
        files = self.files
        self.stem_tokens: list[frozenset[str]] = []
        stem_runs: dict[str, set[tuple[str, ...]]] = {}
        folder_runs: dict[str, set[tuple[str, ...]]] = {}
        for g, members in enumerate(self.groups):
            toks = {t for i in members for t in files.tokens[i]}
            self.stem_tokens.append(frozenset(toks))
            group_runs: set[tuple[str, ...]] = set()
            for i in members:
                stem = files.stems[i]
                if stem not in stem_runs:
                    stem_runs[stem] = set()
                    runs(N.tokenize(self.split_stems[i], split_glued=True), stem_runs[stem])
                group_runs |= stem_runs[stem]
                for f in files.folders[i]:
                    toks.update(N.name_tokens(f))
                    if f not in folder_runs:
                        folder_runs[f] = set()
                        runs(N.name_tokens(f), folder_runs[f])
                    group_runs |= folder_runs[f]
            self.stats.add(g, toks, group_runs)
            if (top := self.tops[g]) is not None:
                self.top_stats[top].add(g, toks, group_runs)

    def _folder_info(self, grp: Group, prefix: Folder, count: int, dist: int) -> dict:
        """What the walk made of a raw folder prefix of the members."""
        res, tree, members = self.res, self.res.tree, grp.members
        eff = tree.effective_of[prefix]
        verdict = res.folders.get(eff)
        name = prefix[-1]
        ident = set(N.name_identity(name))
        under = self.folder_groups.get(eff, set())
        return {
            "depth": len(prefix) - 1,
            "dist": dist,
            "share": count / len(members),
            "transparent": eff == tree.effective_of[prefix[:-1]],
            "container": bool(verdict and verdict.container),
            "named_after": bool(verdict and verdict.named_after_files),
            "variant_only": bool(verdict and verdict.variant_only),
            "files_ratio": verdict.files / len(members) if verdict else 0.0,
            "n_groups": len(under),
            "only_this": under == {grp.index},
            "known": self._known_author(name) is not None,
            "house": sum(bool(ident) and ident <= res.names.stripped[i] for i in members)
            / len(members),
            "global_house": bool(ident) and ident <= res.names.global_house,
            "naming": grp.naming_folder is not None and eff == grp.naming_folder,
            "common": eff == grp.common_eff,
            "is_top": len(prefix) == 1,
            "rendition_name": bool(ident) and all(t in V.REND or t in V.AXIS for t in ident),
            "reason": REASONS.index(verdict.reason) if verdict else -1,
            "generic": tree.name_class.get(eff) is FolderClass.GENERIC,
        }

    def name_all(self, requests: Sequence[Request]) -> list[tuple[str, str | None, bool]]:
        """(name, author, is_identity) of each group, given the rules' choices for it."""
        out = []
        named: list[tuple[int, Group]] = []  # groups the namer scores: (position, group)
        for k, r in enumerate(requests):
            grp = self._group(r.members, r.rule, r.naming_folder)
            cands = name_candidates(self, grp, r.identity_name, r.folder_name)
            if not cands:
                out.append((r.rule.name, r.rule.author, r.rule.is_identity))
                continue
            name, is_identity = self._name(grp, cands)
            out.append((name, None, is_identity))
            named.append((k, grp))
        for (k, _), author in zip(named, self._authors([g for _, g in named]), strict=True):
            out[k] = (out[k][0], author, out[k][2])
        return out

    def _name(self, grp: Group, cands: Cands) -> tuple[str, bool]:
        X = name_features(self, grp, cands)
        scores = self._m.predict("point", X)
        best = self._pick(X, scores)
        ranked = np.sort(scores)
        margin = ranked[1] - ranked[0] if len(scores) > 1 else 0.0
        x_id = np.concatenate([[scores[best], margin], X[best]])[None, :]
        is_identity = bool(self._m.predict("identity", x_id)[0] >= 0.5)
        return self._clean(list(cands.values())[best].text) or grp.rule.name, is_identity

    def _authors(self, grps: Sequence[Group]) -> list[str | None]:
        """The groups' authors, scored over the whole import, or in a library over each group's
        top-level folder.

        The author model was trained on imports of one maker's folder each. On a library of
        many makers' folders its import-wide features (the share of the import's groups, token
        frequencies, the import's size) fall outside that range, and most creators' folders,
        unseen ones above all, end up below the threshold. So when scoring over the whole import
        already credits ``LIBRARY_TOPS`` or more top-level folders as their groups' author, the
        import is a library: each group is scored again over its top-level folder, as if it were
        imported alone, and groups still without an author take the folder when at least half its
        groups have it. A whole-import pick of a folder below the top-level one is kept: scored
        alone, the top folder looks like its groups' maker and would override a creator inside it
        (``Kickstarter/Tom Cartos``). An import of one maker's packs credits at most one pack,
        and keeps the whole-import scores (its packs would otherwise pass for makers); category
        folders ("Forests") are never top-level folders."""
        picks = [self._author(g, self.stats) for g in grps]
        credited = {
            top
            for g, c in zip(grps, picks, strict=True)
            if c is not None and (top := self.tops[g.index]) is not None and self._is(c, top)
        }
        if len(credited) >= LIBRARY_TOPS:
            picks = [
                self._author(g, self.top_stats[top])
                if (top := self.tops[g.index]) is not None and not _below(c, top)
                else c
                for g, c in zip(grps, picks, strict=True)
            ]
            picks = self._fill_from_top(grps, picks)
        return [self._shown(c) if c is not None else None for c in picks]

    def _fill_from_top(
        self, grps: Sequence[Group], picks: list[ACand | None]
    ) -> list[ACand | None]:
        """Groups without an author take their top-level folder when it is the author of at
        least half the groups under it."""
        under: dict[Folder, list[int]] = defaultdict(list)
        for k, g in enumerate(grps):
            if (top := self.tops[g.index]) is not None:
                under[top].append(k)
        out = list(picks)
        for top, ks in under.items():
            hits = [c for k in ks if (c := picks[k]) is not None and self._is(c, top)]
            if 2 * len(hits) >= len(ks):
                for k in ks:
                    if out[k] is None:
                        out[k] = hits[0]
        return out

    def _is(self, c: ACand, folder: Folder) -> bool:
        """Whether an author candidate is the folder (by name or as a known author)."""
        k = author_key(folder[-1])
        keys = {author_key(c.text), author_key(c.raw)}
        known = self.authors.get(k)
        return k in keys or (known is not None and author_key(known) in keys)

    def _shown(self, c: ACand) -> str:
        return self.authors.get(author_key(c.text)) or shown_author(c)

    def _group(
        self, members: Sequence[int], rule: GroupName, naming_folder: Folder | None
    ) -> Group:
        grp = Group(
            self._group_of[members[0]],
            members,
            sample(members, self.files.stems),
            N.common_prefix(self.res.effective[i] for i in members),
            rule,
            naming_folder,
        )
        count: Counter[Folder] = Counter()
        dist: dict[Folder, int] = {}
        for i in members:
            raw = self.files.folders[i]
            for d in range(1, len(raw) + 1):
                count[raw[:d]] += 1
                dist[raw[:d]] = min(dist.get(raw[:d], 99), len(raw) - d)
        grp.folders = {p: self._folder_info(grp, p, n, dist[p]) for p, n in count.items()}
        return grp

    def _pick(self, X: np.ndarray, scores: np.ndarray) -> int:
        """The best candidate: the ``PAIR_K`` best by score, re-ranked by pairwise wins."""
        top = np.argsort(scores, kind="stable")[:PAIR_K]
        if len(top) < 2:
            return int(top[0])
        a, b = (ix.ravel() for ix in np.indices((len(top), len(top))))
        a, b = a[a != b], b[a != b]  # ordered pairs, row-major
        rows = np.column_stack([X[top[a]] - X[top[b]], scores[top[a]] - scores[top[b]]])
        wins = np.bincount(a, weights=self._m.predict("pair", rows), minlength=len(top))
        return int(top[int(np.argmax(wins))])

    def _author(self, grp: Group, stats: Stats) -> ACand | None:
        """The credited author if most members carry one, else the classifier's pick (or none),
        with ``stats`` as the import's statistics."""
        cands, flags = author_candidates(self, stats, grp)
        credited = [
            c
            for c in cands
            if "credit" in c.src and c.credit_share >= 0.5 and not is_frag_word(self.tables, c)
        ]
        if credited:
            return max(credited, key=lambda c: c.credit_share)
        if not cands:
            return None
        X = author_features(self, stats, grp, cands, flags)
        p = self._m.predict("author", X)
        k = int(np.argmax(p))
        return cands[k] if p[k] >= AUTHOR_THRESHOLD else None

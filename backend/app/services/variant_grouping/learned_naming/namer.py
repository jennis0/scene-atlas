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
from .author_features import author_candidates, author_features, is_frag_word
from .name_features import name_candidates, name_features
from .text import Cleaner, author_key, by_split, runs, sample

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser

    from ..naming import GroupName
    from . import LearnedNamer

PAIR_K = 8  # candidates re-ranked pairwise
AUTHOR_THRESHOLD = 0.05
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


class WalkNamer:
    """Names the groups of one walk; import-wide statistics are computed once.

    ``known_author`` maps a folder name to the known author it names; ``authors`` maps
    ``author_key``s to known authors' display names, which replace a predicted author's text."""

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
        self.n_others = max(1, len(self.groups) - 1)
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
        self._index_tokens()

    def _index_tokens(self) -> None:
        """Per token, the number of groups whose paths hold it (``gdf``); per group its stem
        tokens; per token run, the groups whose stems or folder names hold it."""
        files = self.files
        self.gdf: Counter[str] = Counter()
        self.stem_tokens: list[frozenset[str]] = []
        self.run_groups: dict[tuple[str, ...], set[int]] = defaultdict(set)
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
            self.gdf.update(toks)
            for run in group_runs:
                self.run_groups[run].add(g)

    def group_share(self, token: str) -> float:
        """Share of the import's other groups whose paths hold a token."""
        return (self.gdf.get(token, 1) - 1) / self.n_others

    def holders(self, grp: Group, run: tuple[str, ...]) -> set[int]:
        """The groups whose paths hold a token run, this one included."""
        return self.run_groups.get(run, set()) | {grp.index}

    def scope(self, grp: Group) -> set[int]:
        """Groups under the group's effective folder; when it holds only this group, under the
        nearest enclosing folder holding others."""
        folder = grp.common_eff
        while True:
            groups = self.folder_groups.get(folder, {grp.index})
            if len(groups) >= 2 or not folder:
                return groups
            folder = folder[:-1]

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

    def name(
        self,
        members: Sequence[int],
        rule: GroupName,
        naming_folder: Folder | None,
        identity_name: str | None,
        folder_name: str | None,
    ) -> tuple[str, str | None, bool]:
        """(name, author, is_identity) of a group, given the rules' choices for it."""
        grp = self._group(members, rule, naming_folder)
        cands = name_candidates(self, grp, identity_name, folder_name)
        if not cands:
            return rule.name, rule.author, rule.is_identity
        X = name_features(self, grp, cands)
        scores = self._m.predict("point", X)
        best = self._pick(X, scores)
        ranked = np.sort(scores)
        margin = ranked[1] - ranked[0] if len(scores) > 1 else 0.0
        x_id = np.concatenate([[scores[best], margin], X[best]])[None, :]
        is_identity = bool(self._m.predict("identity", x_id)[0] >= 0.5)
        name = self._clean(list(cands.values())[best].text) or rule.name
        author = self._author(grp)
        if author is not None:
            author = self.authors.get(author_key(author), author)
        return name, author, is_identity

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

    def _author(self, grp: Group) -> str | None:
        """The credited author if most members carry one, else the classifier's pick (or none)."""
        cands, flags = author_candidates(self, grp)
        credited = [
            c
            for c in cands
            if "credit" in c.src and c.credit_share >= 0.5 and not is_frag_word(self.tables, c)
        ]
        if credited:
            return max(credited, key=lambda c: c.credit_share).text
        if not cands:
            return None
        X = author_features(self, grp, cands, flags)
        p = self._m.predict("author", X)
        k = int(np.argmax(p))
        return cands[k].text if p[k] >= AUTHOR_THRESHOLD else None

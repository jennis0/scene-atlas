"""The bottom-up tree walk (design/variant-grouping-algorithm.md §7).

Each effective folder P is processed deepest first:

1. **Own files** (stage ``a``). Certain evidence first, then agreement:

   ====  ========================  ===============================================================
   a1    rendition                 pHash within ``rendition_bits`` of 256 and the same aspect
   a2    same-name                 equal identity names (``(levels)``: different floors of one map)
   a3    same-layout               edge correlation **and** embedding cosine high, never against
                                   different name keys; unit-level (a share of cross pairs agree)
   a4    shared-base               the same 2-token key (floors, parts); ``+cohesion`` where gated
                                   (house-prefix folders, families over ``big_family`` units)
   a5    folder-named              the folder's common tokens are the map's name
   a6    variant-only folder       a named leaf folder of files with no identity (``Night.webp``)
   ====  ========================  ===============================================================

   A content split stands unless names or folders give positive evidence.
2. **Container or meaningful**, decided by what a folder *is*, never by how much it holds, so a
   subtree is grouped the same alone or inside a large import. Containers stop the ascent:
   everything below is sealed. A folder is one when it is the root; generically or recurrently
   named; named after a known author; named by a house prefix spread over several of its
   folders (all from names: ``folders``); a **pack** (only child folders, each a map of its own,
   of different productions); or over the ``max_units`` safety cap. ``c0 whole-folder`` lets an
   over-cap or folder-named folder join whole when every unit shares production and theme.
3. **Meaningful parent** (stage ``b``): b1–b4 as a1–a4 across its units, ``b5 unnamed parts``
   (``1st_Floor.png`` inside a folder-named map), and ``c1 parent+cohesion``: units from
   different child folders of one production (aspect, ``NxM``, canvas) join, the parent being
   the evidence and cohesion only the gate. In a specific leaf folder, ``a7 leaf default``: with
   no strong evidence either way the folder decides, so its units join unless content or names
   positively say they are different maps (three-valued evidence: same, different, unknown).
4. **Cross-tree**: ``x1 rendition`` anywhere, except between two large groups. Everything else is
   returned as a suggestion.

Content rules need features; a file without them takes part through names and folders only, so a
paths-only walk is the full walk with every content join withheld.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from . import names as N
from .cohesion import (
    average_linkage,
    cohesive_partition,
    gated_distance,
    production_compatible,
    unit_similarity,
    whole_folder_cohesive,
)
from .evidence import FeatureMatrix, PairSignals, candidate_pairs, pair_signals
from .folders import FolderFacts, folder_facts
from .names import Folder, FolderClass
from .params import EmbeddingThresholds, GroupingParams
from .schema import FolderDecision, FolderReason, FolderVerdict, SubLabel, WalkFiles, WalkResult
from .tree import build_tree
from .vocab import PART_WORDS

# b5: a child unit is "unnamed parts" when this share of its files has no identity of its own.
UNNAMED_PART_SHARE = 0.8
# a7: complete-linkage distance standing in for "positively different" (cosine distances <= 1
# here); the cut sits between, so a unit never joins a cluster holding a map it differs from.
_DIFFERENT = 2.0
_LEAF_CUT = 1.5


class UnionFind:
    """Union-find over file indices, by size (ties: the first argument's root survives)."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> bool:
        a, b = self.find(a), self.find(b)
        if a == b:
            return False
        if self.size[a] < self.size[b]:
            a, b = b, a
        self.parent[b] = a
        self.size[a] += self.size[b]
        return True


def join_agreeing(
    uf: UnionFind,
    pairs: Iterable[tuple[int, int]],
    fraction: float,
    join: Callable[[int, int], object],
) -> None:
    """Layout agreement at unit level: ``join`` two units when >= ``fraction`` of the smaller
    unit's files have an agreeing pair with the other. Pairs are counted on the units as they
    are at the start, so single pairs cannot chain; the most-agreeing unit pairs join first."""
    count: Counter[tuple[int, int]] = Counter()
    example: dict[tuple[int, int], tuple[int, int]] = {}
    for x, y in pairs:
        rx, ry = uf.find(x), uf.find(y)
        if rx == ry:
            continue
        key = (min(rx, ry), max(rx, ry))
        count[key] += 1
        example[key] = (x, y)
    for key, m in count.most_common():
        x, y = example[key]
        if m >= max(1.0, fraction * min(uf.size[uf.find(x)], uf.size[uf.find(y)])):
            join(x, y)


@dataclass
class _Pairs:
    """Content pairs that can join, bucketed by the effective folder their files meet at."""

    signals: PairSignals
    by_lca: dict[Folder, list[int]]


class _Walk:
    """One run of the walk."""

    def __init__(
        self,
        files: WalkFiles,
        fm: FeatureMatrix | None,
        params: GroupingParams,
        known_authors: Collection[str],
    ):
        # The input and what it is: none of this changes during the walk
        self.files = files
        self.p = params
        self.n = n = len(files.stems)
        self.fm = fm if fm is not None and fm.any_content else None
        self.emb = params.embedding if self.fm is not None else None
        self.tree = build_tree(files.folders)
        self.eff = [self.tree.effective_of[f] for f in files.folders]
        self.names = N.analyse_names(files.tokens, files.stems, self.eff)
        self.own: dict[Folder, list[int]] = defaultdict(list)
        self.subtree: dict[Folder, list[int]] = defaultdict(list)
        for i, e in enumerate(self.eff):
            self.own[e].append(i)
            for d in range(len(e) + 1):
                self.subtree[e[:d]].append(i)
        self.facts = folder_facts(
            self.tree, self.names, self.eff, self.own, self.subtree, known_authors
        )
        self.pairs = self._content_pairs()

        # The walk's state: the units, and the files a container has sealed
        self.uf = UnionFind(n)
        self.sealed = np.zeros(n, dtype=bool)

        # What it records: every join (file, reason, folder decision), each folder's verdict and
        # decision, suggestions met on the way, and the folder whose child folders are a group's
        # sub-groups (by group representative; the shallowest wins)
        self.joined: list[tuple[int, str, FolderDecision | None]] = []
        self.verdicts: dict[Folder, FolderVerdict] = {}
        self.decisions: dict[Folder, FolderDecision] = {}
        self.suggestions: list[tuple[int, int, str]] = []
        self.subgroup_parent: dict[int, Folder] = {}

    # ------------------------------------------------------------------ setup

    def _content_pairs(self) -> _Pairs | None:
        """Candidate pairs with rendition / agreement flags, contradictions removed."""
        if self.fm is None:
            return None
        p = self.p
        exhaustive = [idx for idx in self.own.values() if len(idx) <= p.small_folder]
        exhaustive += [
            idx
            for e, idx in self.subtree.items()
            if e and len(idx) <= p.small_subtree and len(idx) > len(self.own.get(e, ()))
        ]
        top_level = {e[:1] for e in self.eff}
        bucket_of = {e: k for k, e in enumerate(sorted(top_level))}
        buckets = np.array([bucket_of[e[:1]] for e in self.eff], dtype=np.int64)
        pairs = candidate_pairs(
            self.fm, exhaustive, p.candidate_phash_bits, p.knn_embedding, p.knn_edge, buckets
        )
        sig = pair_signals(self.fm, pairs, p)
        if sig.agree.any():
            contra = self._contradictions(sig.a, sig.b)
            sig = PairSignals(sig.a, sig.b, sig.rendition, sig.agree & ~contra)
        by_lca: dict[Folder, list[int]] = defaultdict(list)
        for k, (x, y) in enumerate(zip(sig.a.tolist(), sig.b.tolist(), strict=True)):
            by_lca[N.common_prefix((self.eff[x], self.eff[y]))].append(k)
        return _Pairs(sig, by_lca)

    def _contradictions(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Pairs whose names say different maps (see ``NameEvidence.contradict``)."""
        nm = self.names
        return np.fromiter(
            (nm.contradict(x, y) for x, y in zip(a.tolist(), b.tolist(), strict=True)),
            dtype=bool,
            count=len(a),
        )

    # ------------------------------------------------------------------ joins

    def _join(self, x: int, y: int, reason: str, decision: FolderDecision | None) -> bool:
        """Join the units of ``x`` and ``y``, recording why. False if already one unit."""
        if not self.uf.union(x, y):
            return False
        self.joined.append((x, reason, decision))
        return True

    def _units(self, files: Sequence[int]) -> dict[int, list[int]]:
        """Current units (representative -> members, in file order) among ``files``."""
        by_root: dict[int, list[int]] = defaultdict(list)
        for i in files:
            by_root[self.uf.find(i)].append(i)
        return by_root

    def _pairs_at(self, P: Folder) -> tuple[list[int], list[int]]:
        """The content pairs whose files meet at P: (pairs of P's own files, the other pairs
        with neither file sealed)."""
        if self.pairs is None:
            return [], []
        sig = self.pairs.signals
        own: list[int] = []
        cross: list[int] = []
        for k in self.pairs.by_lca.get(P, []):
            x, y = int(sig.a[k]), int(sig.b[k])
            if self.eff[x] == P and self.eff[y] == P:
                own.append(k)
            elif not self.sealed[x] and not self.sealed[y]:
                cross.append(k)
        return own, cross

    def _evidence_joins(
        self, P: Folder, files: Sequence[int], pairs: Sequence[int], stage: str, d: FolderDecision
    ) -> list[int]:
        """a1–a4 among a folder's own files, b1–b4 across a meaningful folder's units:
        renditions and equal names (certain), then layout agreement and shared bases. ``pairs``
        index the content pairs among ``files``. Returns one file of each shared-base join."""
        if self.pairs is not None:
            sig = self.pairs.signals
            for k in pairs:
                if sig.rendition[k]:
                    self._join(int(sig.a[k]), int(sig.b[k]), f"{stage}1 rendition", d)
        self._name_joins(files, stage, d)
        if self.pairs is not None:
            sig = self.pairs.signals
            join_agreeing(
                self.uf,
                ((int(sig.a[k]), int(sig.b[k])) for k in pairs if sig.agree[k]),
                self.p.agree_fraction,
                lambda x, y: self._join(x, y, f"{stage}3 same-layout", d),
            )
        # The same gate in both stages: a leaf must not re-join, ungated, the families a4 split
        return self._shared_base_joins(files, stage, d, self.facts[P].house_gate)

    def _name_joins(self, files: Sequence[int], stage: str, d: FolderDecision) -> None:
        """a2 / b2: equal identity names join; names differing only by level numbers are
        different floors of one map (``(levels)``)."""
        nm = self.names
        family: dict[N.Seq, list[int]] = defaultdict(list)
        for i in files:
            full = nm.full[i]
            if full is not None:
                family[full].append(i)
        for members in family.values():
            if len(members) < 2:
                continue
            by_level: dict[tuple[str, ...], list[int]] = defaultdict(list)
            for i in members:
                by_level[nm.levels[i]].append(i)
            reps = []
            for same_level in by_level.values():
                reps.append(same_level[0])
                for i in same_level[1:]:
                    self._join(same_level[0], i, f"{stage}2 same-name", d)
            for i in reps[1:]:
                self._join(reps[0], i, f"{stage}2 same-name(levels)", d)

    def _cohesive_parts(self, roots: set[int], scope: Sequence[int]) -> list[list[int]]:
        """Partition units (by representative) into cohesive groups, the units' members drawn
        from ``scope``. Without embeddings every unit stands alone: the join is withheld."""
        by_root = {r: m for r, m in self._units(scope).items() if r in roots}
        reps = sorted(by_root)
        if self.fm is None or self.emb is None or len(reps) < 2:
            return [[r] for r in reps]
        parts = cohesive_partition([by_root[r] for r in reps], self.fm, self.files.nxm, self.p)
        return [[reps[k] for k in part] for part in parts]

    def _shared_base_joins(
        self, files: Sequence[int], stage: str, d: FolderDecision, always_gate: bool
    ) -> list[int]:
        """a4 / b4: files sharing a 2-token key join (floors and parts of one map), within a
        series. Gated by cohesion in house-prefix folders (``always_gate``) and for families
        spanning > ``big_family`` units, where a shared base looks like a collection.
        Returns one file of each join made (for sub-group bookkeeping)."""
        nm = self.names
        family: dict[N.Seq, list[int]] = defaultdict(list)
        for i in files:
            key = nm.key2[i]
            if key is not None:
                family[key].append(i)
        joined: list[int] = []
        for members in family.values():
            n_units = len({self.uf.find(i) for i in members})
            if n_units < 2:
                continue
            gated = always_gate or n_units > self.p.big_family
            by_series: dict[frozenset[str], list[int]] = defaultdict(list)
            for i in members:
                by_series[nm.series[i]].append(i)
            for same_series in by_series.values():
                if not gated:
                    parts, reason = [same_series], f"{stage}4 shared-base"
                else:
                    rep = {self.uf.find(i): i for i in same_series}
                    parts = [[rep[r] for r in g] for g in self._cohesive_parts(set(rep), files)]
                    reason = f"{stage}4 shared-base+cohesion"
                for part in parts:
                    for i in part[1:]:
                        if self._join(part[0], i, reason, d):
                            joined.append(part[0])
        return joined

    def _folder_named_joins(self, P: Folder, own: Sequence[int], d: FolderDecision) -> None:
        """a5: the folder's common tokens are the map's name, so its named files that carry
        that name are one map (a minority map in the folder keeps its own)."""
        nm = self.names
        common = set(nm.folder_info[P].common)
        named = [i for i in own if nm.named[i] and common <= nm.unstripped(i)]
        for i in named[1:]:
            self._join(named[0], i, "a5 folder-named", d)

    # ------------------------------------------------------------------ container or meaningful

    def _container(
        self, P: Folder, facts: FolderFacts, active: list[int], n_units: int
    ) -> tuple[FolderReason, str]:
        """(reason, why in words) for a folder holding ``n_units`` units: a container by its
        name, over the unit cap, a pack, or else a candidate location."""
        if facts.sealed_by is not None:
            return facts.sealed_by, facts.sealed_by.value
        if n_units > self.p.max_units:
            return FolderReason.OVER_CAP, f"{n_units} units > {self.p.max_units} (safety cap)"
        why = "candidate location" + (
            " (folder named after its files)" if facts.named_after_files else ""
        )
        if n_units > 1:
            pack, note = self._pack(P, active)
            if pack:
                return FolderReason.PACK, note
            if note:
                why += "; " + note
        return FolderReason.LOCATION, why

    def _pack(self, P: Folder, active: list[int]) -> tuple[bool, str]:
        """(pack?, note): P holds only child folders, each a self-contained map (folder-named,
        or a variant set of >= 2 files), and the children do not all share one production
        (aspect, ``NxM``, canvas). Unknown production (paths only) counts as not shared, so
        content only ever turns a pack into a candidate location (adds joins)."""
        kids: dict[Folder, list[int]] = defaultdict(list)
        for i in active:
            e = self.eff[i]
            if len(e) == len(P):
                return False, ""  # own files: a map with loose renditions, not a pack
            kids[e[: len(P) + 1]].append(i)
        if len(kids) < 2:
            return False, ""
        children = sorted(kids)
        if not all(self.facts[c].folder_named or len(kids[c]) >= 2 for c in children):
            return False, ""
        if self.fm is not None:
            units = [kids[c] for c in children]
            if production_compatible(units, self.fm, self.files.nxm, self.p).all():
                return False, f"children share production ({len(children)} folders)"
        return True, f"pack: {len(children)} self-contained maps of different productions"

    def _whole_folder(
        self, P: Folder, active: list[int], facts: FolderFacts, d: FolderDecision
    ) -> bool:
        """c0: an over-cap or folder-named folder joins whole when every unit shares
        production and theme. Needs structural evidence (child folders or folder-named);
        without it the join becomes a suggestion. Returns whether the folder joined."""
        if self.fm is None or self.emb is None:
            return False
        by_root = self._units(active)
        reps = sorted(by_root)
        whole, stats = whole_folder_cohesive(
            [by_root[r] for r in reps], self.fm, self.files.nxm, self.p
        )
        d.notes.append("whole folder: " + stats.describe())
        if not whole:
            return False
        if facts.leaf and not facts.folder_named:
            reason = "whole folder cohesive, no folder/name evidence (merge as sub-groups?)"
            self.suggestions.extend((reps[0], r, reason) for r in reps[1:])
            return False
        for r in reps[1:]:
            self._join(reps[0], r, "c0 whole-folder", d)
        self.subgroup_parent[self.uf.find(reps[0])] = P
        return True

    # ------------------------------------------------------------------ meaningful parent

    def _part_joins(self, P: Folder, own: list[int], active: list[int], d: FolderDecision) -> None:
        """b5: in a meaningful folder whose own files are one named map, child units whose files
        carry no identity name of their own (``1st_Floor.png``, ``Isolated Floors/…``) are its
        parts: the folder is the evidence, names do not compete."""
        nm = self.names
        named_own = [i for i in own if nm.full[i] is not None]
        if not named_own:
            return
        anchor = named_own[0]
        own_set = set(own)
        for root, members in self._units([i for i in active if i not in own_set]).items():
            if self.uf.find(anchor) == root:
                continue
            unnamed = sum(_is_unnamed_part(nm.full[i]) for i in members)
            if unnamed >= UNNAMED_PART_SHARE * len(members) and self._join(
                anchor, members[0], "b5 unnamed parts", d
            ):
                self.subgroup_parent[self.uf.find(anchor)] = P

    def _home(self, P: Folder, members: Sequence[int]) -> Folder | str | None:
        """The child folder of P holding all of a unit's files; None for P's own files,
        "span" for a unit across several."""
        homes = {self.eff[i][: len(P) + 1] if len(self.eff[i]) > len(P) else None for i in members}
        return homes.pop() if len(homes) == 1 else "span"

    def _parent_joins(self, P: Folder, active: list[int], own_ok: bool, d: FolderDecision) -> None:
        """c1, the parent as evidence: units from different child folders of a meaningful P
        (or own files of a folder-named P) join unless the cohesion / fingerprint gate blocks
        them (average linkage at ``parent``). The fingerprint includes the canvas: one place's
        rooms are drawn to one production. Similarity alone never joins: units of P's own
        files without name evidence become suggestions."""
        if self.fm is None or self.emb is None:
            return
        by_root = self._units(active)
        reps = sorted(by_root)
        m = len(reps)
        if m < 2:
            return
        units = [by_root[r] for r in reps]
        sim = unit_similarity(units, self.fm, self.files.nxm, self.p, canvas=True)
        homes = [self._home(P, u) for u in units]
        structural = np.array(
            [[own_ok if hx is None and hy is None else hx != hy for hy in homes] for hx in homes]
        )
        labels = average_linkage(gated_distance(sim, structural), 1.0 - self.emb.parent)
        iu = np.triu_indices(m, 1)
        allowed = (sim.compatible & structural)[iu]
        d.notes.append(
            f"parent cohesion mean {sim.cohesion[iu].mean():.2f} min {sim.cohesion[iu].min():.2f}"
            f" fp-compatible {allowed.mean():.2f} over {m} units"
        )
        for lab in np.unique(labels):
            members = [reps[k] for k in np.flatnonzero(labels == lab)]
            for r in members[1:]:
                if self._join(members[0], r, "c1 parent+cohesion", d):
                    self.subgroup_parent[self.uf.find(members[0])] = P
        for x, y in zip(*iu, strict=True):
            if (
                labels[x] != labels[y]
                and sim.compatible[x, y]
                and sim.cohesion[x, y] >= self.emb.suggest
            ):
                why = (
                    "parent+cohesion(near)"
                    if structural[x, y]
                    else "cohesive, no folder/name evidence"
                )
                self.suggestions.append((units[x][0], units[y][0], why))

    def _leaf_default(self, active: list[int], facts: FolderFacts, d: FolderDecision) -> None:
        """a7: a specific, non-container leaf folder is one map unless shown otherwise. With no
        strong evidence either way its units join by complete linkage: a unit joins a cluster
        only if it is not positively different (``_different``) from any member. Needs
        embeddings, so the paths-only walk withholds it and content only adds joins."""
        if self.fm is None or self.emb is None or not facts.leaf or not facts.specific:
            return
        by_root = self._units(active)
        reps = sorted(by_root)
        m = len(reps)
        if m < 2 or m > self.p.max_units:
            return
        units = [by_root[r] for r in reps]
        different, cohesion = self._different(units, self.fm, self.emb, facts.named_after_files)
        distance = np.where(different, _DIFFERENT, np.clip(1.0 - cohesion, 0.0, 1.0))
        np.fill_diagonal(distance, 0.0)
        iu = np.triu_indices(m, 1)
        labels = fcluster(linkage(distance[iu], method="complete"), _LEAF_CUT, "distance")
        d.notes.append(
            f"leaf default: {m} units, {int(different[iu].sum())}/{len(iu[0])} different"
        )
        for lab in np.unique(labels):
            members = [reps[k] for k in np.flatnonzero(labels == lab)]
            for r in members[1:]:
                self._join(members[0], r, "a7 leaf default", d)

    def _different(
        self,
        units: list[list[int]],
        fm: FeatureMatrix,
        emb: EmbeddingThresholds,
        named_after_files: bool,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(different, cohesion) between the units of a leaf folder: (m, m) positive evidence
        that two units are different maps, and their (layout-raised) cohesion.

        Different when cohesion is below ``leaf_different``; else never if the folder is named
        after its files (its names and variant sets are parts of the map it names); else when the
        **names differ** (no shared head word, or different series: ``Volcanic Path`` /
        ``Volcanic Path Vol2``) and either both units are variant sets or the folder has catalog
        names (nearly every keyed file a key of its own); else, with one weak cue (names differ,
        or both units are variant sets), unless they share one production at
        ``leaf_same_production`` or reach ``leaf_same``. The head word, not shared words: one
        maker's maps share topic words (``forest path`` / ``rocky forest``), one map's variant
        sets share its head (``airships deck`` / ``airships hull``)."""
        nm = self.names
        cohesion = unit_similarity(units, fm, self.files.nxm, self.p).cohesion
        one_production = production_compatible(units, fm, self.files.nxm, self.p)
        keyed = [nm.veto_key[i] for u in units for i in u if nm.veto_key[i] is not None]
        catalog = len(keyed) >= 3 and len(set(keyed)) >= N.COMMON_SHARE * len(keyed)
        series = [frozenset().union(*(nm.series[i] for i in u)) for u in units]
        heads = [frozenset(full[0] for i in u if (full := nm.full[i])) for u in units]
        m = len(units)
        different = np.zeros((m, m), dtype=bool)
        for x in range(m):
            for y in range(x + 1, m):
                c = cohesion[x, y]
                if c < emb.leaf_different:
                    different[x, y] = True
                    continue
                if named_after_files:
                    continue
                names_differ = bool(heads[x] and heads[y]) and (
                    not heads[x] & heads[y] or series[x] != series[y]
                )
                variant_sets = len(units[x]) >= 2 and len(units[y]) >= 2
                if names_differ and (variant_sets or catalog):
                    different[x, y] = True
                elif names_differ or variant_sets:
                    same = (one_production[x, y] and c >= emb.leaf_same_production) or (
                        c >= emb.leaf_same
                    )
                    different[x, y] = not same
        different |= different.T
        return different, cohesion

    # ------------------------------------------------------------------ one folder

    def _visit(self, P: Folder) -> None:
        facts = self.facts[P]
        own = self.own.get(P, [])
        d = self.decisions[P] = FolderDecision("/".join(P))
        own_pairs, cross_pairs = self._pairs_at(P)

        # 1. Its own files (stage a)
        self._evidence_joins(P, own, own_pairs, "a", d)
        info = self.names.folder_info.get(P)
        if info is not None:
            d.names = info.describe()
        if facts.named_map:
            self._folder_named_joins(P, own, d)
        if facts.variant_only:
            for i in own[1:]:
                self._join(own[0], i, "a6 variant-only folder", d)

        # 2. Container or meaningful
        active = [i for i in self.subtree.get(P, []) if not self.sealed[i]]
        n_units = len({self.uf.find(i) for i in active})
        d.units_before = n_units
        reason, why = self._container(P, facts, active, n_units)
        container = reason is not FolderReason.LOCATION
        if (
            (reason is FolderReason.OVER_CAP or (not container and facts.folder_named))
            and 1 < n_units <= self.p.whole_folder_max_units
            and self._whole_folder(P, active, facts, d)
        ):
            reason, container, why = FolderReason.LOCATION, False, why + "; whole folder cohesive"
        d.container, d.why = container, why
        self.verdicts[P] = FolderVerdict(
            container=container,
            reason=reason,
            named_after_files=facts.named_after_files,
            variant_only=facts.variant_only,
            files=len(self.subtree.get(P, ())),
        )

        # 3. A meaningful folder joins its units (stage b)
        if not container and n_units > 1:
            for i in self._evidence_joins(P, active, cross_pairs, "b", d):
                self.subgroup_parent[self.uf.find(i)] = P
            if facts.named_map:
                self._part_joins(P, own, active, d)
            self._parent_joins(P, active, facts.folder_named, d)
            self._leaf_default(active, facts, d)
        d.units_after = len({self.uf.find(i) for i in active})
        if container:
            self.sealed[self.subtree.get(P, [])] = True

    # ------------------------------------------------------------------ cross-tree

    def _cross_tree(self) -> list[tuple[int, int, str]]:
        """Step 4: renditions anywhere, unless both groups are large."""
        suggestions: list[tuple[int, int, str]] = []
        if self.pairs is None:
            return suggestions
        sig = self.pairs.signals
        for k in np.flatnonzero(sig.rendition).tolist():
            x, y = int(sig.a[k]), int(sig.b[k])
            rx, ry = self.uf.find(x), self.uf.find(y)
            if rx == ry:
                continue
            if min(self.uf.size[rx], self.uf.size[ry]) >= self.p.big_join:
                suggestions.append((x, y, "rendition(two large groups)"))
            else:
                self._join(x, y, "x1 rendition", None)
        return suggestions

    def _keyed_units(self, keys: Sequence[N.Seq | None]) -> dict[N.Seq, dict[int, int]]:
        """Per key, the units holding it: representative -> its first file with the key."""
        out: dict[N.Seq, dict[int, int]] = defaultdict(dict)
        for i, key in enumerate(keys):
            if key is not None:
                out[key].setdefault(self.uf.find(i), i)
        return out

    def _tree_suggestions(self) -> list[tuple[int, int, str]]:
        """Cross-tree joins the walk does not make, with reasons."""
        nm = self.names
        find = self.uf.find
        out: list[tuple[int, int, str]] = []
        names = [g if f is not None else None for g, f in zip(nm.cross_tree, nm.full, strict=True)]
        for units in self._keyed_units(names).values():
            roots = sorted(units)
            if 1 < len(roots) <= 3:
                out.extend((units[roots[0]], units[r], "same-name across tree") for r in roots[1:])
        agreeing: set[tuple[int, int]] = set()
        if self.pairs is not None:
            sig = self.pairs.signals
            for k in np.flatnonzero(sig.agree).tolist():
                x, y = int(sig.a[k]), int(sig.b[k])
                rx, ry = find(x), find(y)
                if rx != ry:
                    agreeing.add((min(rx, ry), max(rx, ry)))
                    if nm.key2[x] is None or nm.key2[y] is None:
                        out.append((x, y, "same-layout across tree"))
        for units in self._keyed_units(nm.key2).values():
            roots = sorted(units)
            if 1 < len(roots) <= 6:
                out.extend(
                    (units[a], units[b], "same-base+layout across tree")
                    for a, b in combinations(roots, 2)
                    if (a, b) in agreeing
                )
        same_name: dict[str, set[Folder]] = defaultdict(set)
        first_in: dict[Folder, int] = {}
        for i, e in enumerate(self.eff):
            if e and self.tree.name_class.get(e) is FolderClass.SPECIFIC:
                same_name[e[-1]].add(e)
                first_in.setdefault(e, i)
        for folders in same_name.values():
            if 1 < len(folders) <= 3:
                reps = [first_in[e] for e in sorted(folders)]
                out.extend((reps[0], i, "same-named folder") for i in reps[1:])
        return out

    # ------------------------------------------------------------------ labels

    def _sublabels(self, root: list[int]) -> list[SubLabel | None]:
        """Sub-group labels: the child folders of the shallowest parent join, else level names
        when a group has >= 2 of them, else none."""
        parent: dict[int, Folder] = {}
        for r, P in self.subgroup_parent.items():
            g = self.uf.find(r)
            if g not in parent or len(P) < len(parent[g]):
                parent[g] = P
        levels = [N.level_tag(t) for t in self.files.tokens]
        group_levels: dict[int, set[str]] = defaultdict(set)
        for i, lv in enumerate(levels):
            if lv is not None:
                group_levels[root[i]].add(lv)
        out: list[SubLabel | None] = []
        for i, g in enumerate(root):
            P = parent.get(g)
            if P is not None:
                e = self.eff[i]
                out.append(SubLabel("folder", e[: len(P) + 1]) if len(e) > len(P) else None)
            elif len(group_levels[g]) >= 2 and (level := levels[i]) is not None:
                out.append(SubLabel("level", level))
            else:
                out.append(None)
        return out

    def run(self) -> WalkResult:
        for P in sorted(self.facts, key=lambda f: (-len(f), f)):
            self._visit(P)
        suggestions = self._cross_tree() + self._tree_suggestions() + self.suggestions
        root = [self.uf.find(i) for i in range(self.n)]
        reasons: dict[int, Counter[str]] = defaultdict(Counter)
        for i, reason, decision in self.joined:
            reasons[root[i]][reason] += 1
            if decision is not None:
                decision.joins[reason] += 1
        return WalkResult(
            root=root,
            sublabel=self._sublabels(root),
            suggestions=[(x, y, r) for x, y, r in suggestions if root[x] != root[y]],
            reasons=dict(reasons),
            folders=self.verdicts,
            decisions=self.decisions,
            effective=self.eff,
            tree=self.tree,
            names=self.names,
        )


def _is_unnamed_part(identity: N.Seq | None) -> bool:
    """A file with no identity of its own, or one made only of part words ("1st Floor")."""
    return identity is None or set(identity) <= PART_WORDS


def run_walk(
    files: WalkFiles,
    features: FeatureMatrix | None,
    params: GroupingParams,
    known_authors: Collection[str] = (),
) -> WalkResult:
    """Run the walk over ``files`` (with content ``features``, or None for paths only).
    ``known_authors`` are the ``names.name_key``s of creators already in the library: a folder
    named after one is a container."""
    return _Walk(files, features, params, known_authors).run()

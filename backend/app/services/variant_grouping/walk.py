"""The bottom-up tree walk (design/variant-grouping.md §2), narrow mode.

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
2. **Container or meaningful.** Containers (root, generic / recurring / house-prefix name, too
   many units) stop the ascent: everything below is sealed. ``c0 whole-folder`` lets an
   over-cap or folder-named folder join whole when every unit shares production and theme.
3. **Meaningful parent** (stage ``b``): b1–b4 as a1–a4 across its units, ``b5 unnamed parts``
   (``1st_Floor.png`` inside a folder-named map), and ``c1 parent+cohesion``: units from
   different child folders join, the parent being the evidence and cohesion only the gate.
4. **Cross-tree** (narrow): ``x1 rendition`` anywhere, except between two large groups.
   Everything else is returned as a suggestion.

Content rules need features; a file without them takes part through names and folders only, so a
paths-only walk is the full walk with every content join withheld. Ported from
scene-atlas-learning ``grouping/e5/walk.py`` (``mode="narrow"``, E5 defaults).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from . import names as N
from .cohesion import (
    CohesionParams,
    average_linkage,
    cohesive_partition,
    gated_distance,
    unit_similarity,
    whole_folder_cohesive,
)
from .evidence import FeatureMatrix, PairSignals, PairThresholds, candidate_pairs, pair_signals
from .names import Folder, FolderClass, NameEvidence
from .tree import EffectiveTree, build_tree
from .vocab import GENERIC, PART_WORDS

# b5: a child unit is "unnamed parts" when this share of its files has no identity of its own.
UNNAMED_PART_SHARE = 0.8
# a6: a named leaf folder is one map when this share of its files has no identity at all
# (``Golden Forest/Night.webp``). The parser's ``group_files`` Pass 0 uses 0.7 for its rule.
VARIANT_ONLY_SHARE = 0.8


@dataclass(frozen=True)
class EmbeddingThresholds:
    """Embedding thresholds; they depend on the encoder (design §5).

    Defaults are E5's, tuned on siglip2_base_384_rc4 image embeddings.
    """

    agree: float = 0.70  # a3 / b3: embedding cosine of an agreeing pair (with the edge map)
    parent: float = 0.82  # c1: unit cohesion that lets a meaningful parent join its units
    whole_folder: float = 0.80  # c0: mean cohesion over every unit pair of the folder
    shared_base: float = 0.68  # a4 / b4 gate: cohesion of a gated shared-base family
    suggest: float = 0.66  # cohesion of a parent near-miss worth suggesting


@dataclass(frozen=True)
class GroupingParams:
    """Thresholds of the walk. Defaults are E5's (tuned on the research benchmark, dev split).

    ``embedding`` is None when no calibration matches the active encoder: every rule that needs
    an embedding is then off (renditions, names and folders still work).
    """

    rendition_bits: int = 12  # pHash Hamming bits of 256 (dev precision 0.999)
    rendition_aspect: float = 0.02  # |log aspect| difference of renditions
    agree_edge: float = 0.70  # edge-map correlation of an agreeing pair
    agree_aspect: float = 0.05
    agree_fraction: float = 0.25  # share of cross pairs that must agree to join two units
    big_family: int = 8  # a shared base over more units than this looks like a collection
    layout_overlap: float = 0.25  # mean cross edge correlation that raises unit cohesion
    aspect_tolerance: float = 0.03  # fingerprint: |log aspect| difference of compatible units
    whole_folder_compatible: float = 0.9  # c0: share of unit pairs with compatible fingerprints
    whole_folder_max_units: int = 200  # c0 is not tried on folders with more units
    max_units: int = 8  # a folder with more units is a container
    max_units_named: int = 60  # ... unless it is named after its files
    small_folder: int = 80  # all pairs are compared inside folders this small
    small_subtree: int = 150  # ... and inside subtrees this small
    big_join: int = 20  # x1 between two groups both this large becomes a suggestion
    candidate_phash_bits: int = 20  # pHash candidate pairs (renditions need rendition_bits)
    knn_embedding: int = 25  # candidate neighbours per file by embedding
    knn_edge: int = 15  # candidate neighbours per file by edge map
    embedding: EmbeddingThresholds | None = None

    def pair_thresholds(self) -> PairThresholds:
        return PairThresholds(
            rendition_bits=self.rendition_bits,
            rendition_aspect=self.rendition_aspect,
            agree_edge=self.agree_edge,
            agree_embedding=self.embedding.agree if self.embedding else None,
            agree_aspect=self.agree_aspect,
        )


@dataclass
class FolderDecision:
    """What the walk decided at one effective folder (for DEBUG logging)."""

    folder: str
    own_files: int
    subtree_files: int
    units_before: int = 0
    units_after: int = 0
    container: bool = False
    folder_named: bool = False  # named after its files, or its files' common name is the map's
    named_after_files: bool = False  # the folder's own name is its files' common name
    variant_only: bool = False  # a6: a named folder of files without identity, so one map
    why: str = ""
    names: str = ""
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
            tokens.append(N.tokenize(stem))
            nxm.append(N.nxm_of(stem))
        return cls(folders, stems, tokens, nxm)


@dataclass
class WalkResult:
    """The walk's output, by file index (walk order)."""

    root: list[int]  # group representative per file
    sublabel: list[SubLabel | None]
    suggestions: list[tuple[int, int, str]]  # (file, file, reason) across different groups
    reasons: dict[int, Counter[str]]  # group representative -> join reasons
    decisions: dict[Folder, FolderDecision]
    effective: list[Folder]  # effective folder per file
    tree: EffectiveTree
    names: NameEvidence


class _UnionFind:
    """Union-find with union by size (ties: the first argument's root survives)."""

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


def _folder_text(folder: Folder) -> str:
    return "/".join(folder)


@dataclass
class _Pairs:
    """Content pairs that can join, bucketed by the effective folder of their LCA."""

    signals: PairSignals
    by_lca: dict[Folder, list[int]]


class _Walk:
    """One run of the walk. State: the union-find, sealed files and sub-group parents."""

    def __init__(self, files: WalkFiles, fm: FeatureMatrix | None, params: GroupingParams):
        self.files = files
        self.p = params
        self.n = n = len(files.stems)
        self.fm = fm if fm is not None and fm.any_content else None
        self.emb = params.embedding if self.fm is not None else None
        self.cohesion = (
            CohesionParams(self.emb.parent, params.layout_overlap, params.aspect_tolerance)
            if self.emb is not None
            else None
        )
        self.tree = build_tree(files.folders)
        self.eff = [self.tree.effective_of[f] for f in files.folders]
        self.names = N.analyse_names(files.tokens, files.stems, self.eff)
        self.recurring = self.tree.recurring_names()
        self.uf = _UnionFind(n)
        self.sealed = np.zeros(n, dtype=bool)
        self.reasons: list[tuple[int, str]] = []  # (file, join reason), resolved to groups at end
        self.decisions: dict[Folder, FolderDecision] = {}
        self.near: list[tuple[int, int, str]] = []
        # group representative -> folder whose child folders are its sub-groups (shallowest wins)
        self.subgroup_parent: dict[int, Folder] = {}

        self.own: dict[Folder, list[int]] = defaultdict(list)
        self.subtree: dict[Folder, list[int]] = defaultdict(list)
        for i, e in enumerate(self.eff):
            self.own[e].append(i)
            for d in range(len(e) + 1):
                self.subtree[e[:d]].append(i)
        self.pairs = self._content_pairs()

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
        sig = pair_signals(self.fm, pairs, p.pair_thresholds())
        if sig.agree.any():
            contra = self._contradictions(sig.a, sig.b)
            sig = PairSignals(sig.a, sig.b, sig.rendition, sig.agree & ~contra)
        by_lca: dict[Folder, list[int]] = defaultdict(list)
        for k, (x, y) in enumerate(zip(sig.a.tolist(), sig.b.tolist(), strict=True)):
            by_lca[_lca(self.eff[x], self.eff[y])].append(k)
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
        self.reasons.append((x, reason))
        if decision is not None:
            decision.joins[reason] += 1
        return True

    def _units(self, files: Sequence[int]) -> dict[int, list[int]]:
        """Current units (representative -> members, in file order) among ``files``."""
        by_root: dict[int, list[int]] = defaultdict(list)
        for i in files:
            by_root[self.uf.find(i)].append(i)
        return by_root

    def _rendition_joins(
        self, sig: PairSignals, ks: Sequence[int], reason: str, d: FolderDecision
    ) -> None:
        """a1 / b1: renditions (certain evidence) join outright."""
        for k in ks:
            if sig.rendition[k]:
                self._join(int(sig.a[k]), int(sig.b[k]), reason, d)

    def _name_joins(
        self, files: Sequence[int], stage: str, d: FolderDecision, cross_only: bool = False
    ) -> None:
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
            if cross_only and len({self.uf.find(i) for i in members}) < 2:
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

    def _agree_joins(
        self, sig: PairSignals, ks: Sequence[int], stage: str, d: FolderDecision
    ) -> None:
        """a3 / b3: join two units when >= ``agree_fraction`` of the smaller unit's files have
        an agreeing pair with the other (counted on the units at the start), so single pairs
        cannot chain."""
        count: Counter[tuple[int, int]] = Counter()
        rep: dict[tuple[int, int], tuple[int, int]] = {}
        for k in ks:
            if not sig.agree[k]:
                continue
            x, y = int(sig.a[k]), int(sig.b[k])
            rx, ry = self.uf.find(x), self.uf.find(y)
            if rx == ry:
                continue
            key = (min(rx, ry), max(rx, ry))
            count[key] += 1
            rep[key] = (x, y)
        for key, m in count.most_common():
            ra, rb = key
            smaller = min(self.uf.size[self.uf.find(ra)], self.uf.size[self.uf.find(rb)])
            if m >= max(1.0, self.p.agree_fraction * smaller):
                self._join(*rep[key], f"{stage}3 same-layout", d)

    def _cohesive_parts(self, roots: set[int], scope: Sequence[int]) -> list[list[int]]:
        """Partition units (by representative) into cohesive groups, the units' members drawn
        from ``scope``. Without embeddings every unit stands alone: the join is withheld."""
        by_root = {r: m for r, m in self._units(scope).items() if r in roots}
        reps = sorted(by_root)
        if self.cohesion is None or self.fm is None or self.emb is None or len(reps) < 2:
            return [[r] for r in reps]
        parts = cohesive_partition(
            [by_root[r] for r in reps],
            self.fm,
            self.files.nxm,
            self.cohesion,
            self.emb.shared_base,
        )
        return [[reps[k] for k in part] for part in parts]

    def _shared_base_joins(
        self,
        files: Sequence[int],
        stage: str,
        d: FolderDecision,
        always_gate: bool,
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

    def _folder_named_joins(self, own: Sequence[int], d: FolderDecision) -> None:
        """a5: the folder's common tokens are the map's name, so its named files are one map."""
        named = [i for i in own if self.names.named[i]]
        for i in named[1:]:
            self._join(named[0], i, "a5 folder-named", d)

    # ------------------------------------------------------------------ folder tests

    def _named_after_files(self, P: Folder) -> bool:
        """The folder is named after its files' common name (>= 2 identity tokens shared)."""
        if not P:
            return False
        folder_tokens = set(N.name_identity(P[-1])) - GENERIC
        common = self.names.common_raw.get(P, set()) - GENERIC
        return len(folder_tokens & common) >= 2 and (
            folder_tokens <= common or common <= folder_tokens
        )

    def _folder_named(self, P: Folder) -> bool:
        """Structural evidence that a folder is one map: named after its files, or its files'
        common tokens are the map's name."""
        info = self.names.folder_info.get(P)
        return self._named_after_files(P) or bool(info and info.named_map)

    def _container(self, P: Folder, n_units: int) -> tuple[bool, str, bool]:
        """(container?, why, over the unit cap?) for a folder holding ``n_units`` units."""
        if not P:
            return True, "root", False
        if self.tree.name_class.get(P) is FolderClass.GENERIC:
            return True, "generic name", False
        if P[-1] in self.recurring:
            return True, "recurring name (author/topic folder)", False
        folder_tokens = set(N.name_identity(P[-1]))
        if folder_tokens and folder_tokens <= self.names.global_house:
            return True, "house-prefix name (author/collection folder)", False
        named_after = self._named_after_files(P)
        cap = self.p.max_units_named if named_after else self.p.max_units
        suffix = " (folder named after its files)" if named_after else ""
        if n_units > cap:
            return True, f"{n_units} units > {cap}{suffix}", True
        return False, f"candidate location{suffix}", False

    # ------------------------------------------------------------------ per-folder steps

    def _own_files(self, P: Folder, d: FolderDecision) -> list[int]:
        """Step 1 (stage a): link a folder's own files. Returns the folder's own pairs."""
        own = self.own.get(P, [])
        own_pairs: list[int] = []
        if self.pairs is not None:
            own_set = set(own)
            sig = self.pairs.signals
            own_pairs = [
                k
                for k in self.pairs.by_lca.get(P, [])
                if int(sig.a[k]) in own_set and int(sig.b[k]) in own_set
            ]
            self._rendition_joins(sig, own_pairs, "a1 rendition", d)
        self._name_joins(own, "a", d)
        if self.pairs is not None:
            self._agree_joins(self.pairs.signals, own_pairs, "a", d)
        info = self.names.folder_info.get(P)
        self._shared_base_joins(own, "a", d, always_gate=bool(info and info.house))
        if info is not None:
            d.names = info.describe()
            if info.named_map:
                self._folder_named_joins(own, d)
        if self._variant_only_folder(P, own):
            d.variant_only = True
            for i in own[1:]:
                self._join(own[0], i, "a6 variant-only folder", d)
        return own_pairs

    def _variant_only_folder(self, P: Folder, own: Sequence[int]) -> bool:
        """a6 (deviation from E5, follow-up 2): a specific-named leaf folder whose files carry
        no identity (``Golden Forest/Night.webp``, ``Day.webp``) is one map, named by the
        folder. Structural evidence, so it joins at seal, as ``ImageParser.group_files`` does.
        Generic, recurring and house-prefix folder names never qualify."""
        if not P or len(own) < 2 or self.tree.children.get(P):
            return False
        if self.tree.name_class.get(P) is not FolderClass.SPECIFIC or P[-1] in self.recurring:
            return False
        folder_tokens = set(N.name_identity(P[-1]))
        if folder_tokens <= self.names.global_house:
            return False
        unnamed = sum(self.names.variant_only[i] for i in own)
        return unnamed >= VARIANT_ONLY_SHARE * len(own)

    def _whole_folder(
        self, P: Folder, roots: list[int], active: list[int], d: FolderDecision
    ) -> bool:
        """c0 (E5 fix 0b): an over-cap or folder-named folder joins whole when every unit shares
        production and theme. Needs structural evidence (child folders or folder-named);
        without it the join becomes a suggestion. Returns whether the folder joined."""
        if self.cohesion is None or self.fm is None or self.emb is None:
            return False
        by_root = self._units(active)
        reps = sorted(r for r in by_root if r in set(roots))
        whole, stats = whole_folder_cohesive(
            [by_root[r] for r in reps],
            self.fm,
            self.files.nxm,
            self.cohesion,
            self.emb.whole_folder,
            self.p.whole_folder_compatible,
        )
        d.notes.append("whole folder: " + stats.describe())
        if not whole:
            return False
        structural = bool(self.tree.children.get(P)) or self._folder_named(P)
        if not structural:
            reason = "whole folder cohesive, no folder/name evidence (merge as sub-groups?)"
            self.near.extend((reps[0], r, reason) for r in reps[1:])
            return False
        for r in reps[1:]:
            self._join(reps[0], r, "c0 whole-folder", d)
        self.subgroup_parent[self.uf.find(reps[0])] = P
        return True

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
        them (average linkage at ``parent``). Similarity alone never joins: units of P's own
        files without name evidence become suggestions."""
        if self.cohesion is None or self.fm is None or self.emb is None:
            return
        by_root = self._units(active)
        reps = sorted(by_root)
        m = len(reps)
        if m < 2:
            return
        units = [by_root[r] for r in reps]
        sim = unit_similarity(units, self.fm, self.files.nxm, self.cohesion)
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
                self.near.append((units[x][0], units[y][0], why))

    def _meaningful_parent(
        self, P: Folder, own: list[int], own_pairs: list[int], active: list[int], d: FolderDecision
    ) -> None:
        """Step 3 (stage b): join a meaningful folder's units."""
        if self.pairs is not None:
            bucket = self.pairs.by_lca.get(P, [])
            sig = self.pairs.signals
            in_own = set(own_pairs)
            cross = [
                k
                for k in bucket
                if k not in in_own
                and not self.sealed[int(sig.a[k])]
                and not self.sealed[int(sig.b[k])]
            ]
            self._rendition_joins(sig, cross, "b1 rendition", d)
        else:
            cross = []
        self._name_joins(active, "b", d, cross_only=True)
        if self.pairs is not None:
            self._agree_joins(self.pairs.signals, cross, "b", d)
        for i in self._shared_base_joins(active, "b", d, always_gate=False):
            self.subgroup_parent[self.uf.find(i)] = P
        info = self.names.folder_info.get(P)
        if info is not None and info.named_map:
            self._part_joins(P, own, active, d)
        self._parent_joins(P, active, self._folder_named(P), d)

    def _visit(self, P: Folder) -> None:
        own = self.own.get(P, [])
        d = FolderDecision(_folder_text(P), len(own), len(self.subtree.get(P, ())))
        self.decisions[P] = d
        own_pairs = self._own_files(P, d)

        active = [i for i in self.subtree.get(P, []) if not self.sealed[i]]
        roots = sorted({self.uf.find(i) for i in active})
        d.units_before = len(roots)
        container, why, over_cap = self._container(P, len(roots))
        folder_named = d.folder_named = self._folder_named(P)
        d.named_after_files = self._named_after_files(P)
        if (
            (over_cap or (not container and folder_named and len(roots) > 1))
            and len(roots) <= self.p.whole_folder_max_units
            and self._whole_folder(P, roots, active, d)
        ):
            container, why = False, why + "; whole folder cohesive"
        d.container, d.why = container, why
        if not container and len(roots) > 1:
            self._meaningful_parent(P, own, own_pairs, active, d)
        d.units_after = len({self.uf.find(i) for i in active})
        if container:
            self.sealed[self.subtree.get(P, [])] = True

    # ------------------------------------------------------------------ cross-tree

    def _cross_tree(self) -> list[tuple[int, int, str]]:
        """Step 4 (narrow): renditions anywhere, unless both groups are large."""
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

    def _tree_suggestions(self) -> list[tuple[int, int, str]]:
        """Cross-tree joins narrow mode does not make, with reasons (E5 ``_global_candidates``)."""
        nm = self.names
        find = self.uf.find
        out: list[tuple[int, int, str]] = []

        def by_key(keys: Sequence[N.Seq | None], reason: str, max_groups: int) -> None:
            groups: dict[N.Seq, list[int]] = defaultdict(list)
            first: dict[tuple[N.Seq, int], int] = {}
            for i, key in enumerate(keys):
                if key is None:
                    continue
                r = find(i)
                if (key, r) not in first:
                    first[(key, r)] = i
                    groups[key].append(r)
            for key, roots in groups.items():
                if 1 < len(roots) <= max_groups:
                    roots = sorted(roots)
                    out.extend((first[(key, roots[0])], first[(key, r)], reason) for r in roots[1:])

        by_key(
            [g if f is not None else None for g, f in zip(nm.cross_tree, nm.full, strict=True)],
            "same-name across tree",
            max_groups=3,
        )
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
        groups: dict[N.Seq, list[int]] = defaultdict(list)
        first: dict[tuple[N.Seq, int], int] = {}
        for i, key in enumerate(nm.key2):
            if key is None:
                continue
            r = find(i)
            if (key, r) not in first:
                first[(key, r)] = i
                groups[key].append(r)
        for key, roots in groups.items():
            roots = sorted(roots)
            if 1 < len(roots) <= 6:
                for x in range(len(roots)):
                    for y in range(x + 1, len(roots)):
                        if (roots[x], roots[y]) in agreeing:
                            out.append(
                                (
                                    first[(key, roots[x])],
                                    first[(key, roots[y])],
                                    "same-base+layout across tree",
                                )
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
        when a group has >= 2 of them, else none (design §2, last paragraph)."""
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
        every: set[Folder] = set(self.subtree) | set(self.tree.children)
        for P in sorted(every, key=lambda f: (-len(f), f)):
            self._visit(P)
        suggestions = self._cross_tree()
        suggestions += self._tree_suggestions()
        suggestions += self.near
        root = [self.uf.find(i) for i in range(self.n)]
        reasons: dict[int, Counter[str]] = defaultdict(Counter)
        for i, reason in self.reasons:
            reasons[root[i]][reason] += 1
        return WalkResult(
            root=root,
            sublabel=self._sublabels(root),
            suggestions=[(x, y, r) for x, y, r in suggestions if root[x] != root[y]],
            reasons=dict(reasons),
            decisions=self.decisions,
            effective=self.eff,
            tree=self.tree,
            names=self.names,
        )


def _is_unnamed_part(identity: N.Seq | None) -> bool:
    """A file with no identity of its own, or one made only of part words ("1st Floor")."""
    return identity is None or set(identity) <= PART_WORDS


def _lca(a: Folder, b: Folder) -> Folder:
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return a[:k]


def run_walk(
    files: WalkFiles, features: FeatureMatrix | None, params: GroupingParams
) -> WalkResult:
    """Run the walk over ``files`` (with content ``features``, or None for paths only)."""
    return _Walk(files, features, params).run()

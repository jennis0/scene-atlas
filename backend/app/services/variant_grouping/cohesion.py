"""Unit-level content gates: theme cohesion and the production fingerprint (design §2, step 3).

A *unit* is a set of files already joined. At a meaningful parent folder, units join as
sub-groups only where content does not object: their **cohesion** (mean cross embedding cosine,
raised when their layouts overlap: the same building drawn again) is high, and their
**production fingerprint** (aspect ratio; ``NxM`` where both name one) is compatible. Cohesion
only ever gates a join that the folder structure or the names propose; it is never the reason
for one.

A unit with no embedding, or no known aspect, is never compatible: the join is withheld.
Ported from scene-atlas-learning ``grouping/e5/walk.py`` (``_unit_sim``, ``_cohesive``,
``_whole_folder``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from .evidence import FeatureMatrix

# Distance standing in for "incompatible" in average linkage (cosine distances are <= 2).
INCOMPATIBLE = 2.0
# Layout overlap raises a pair's cohesion to just above the parent threshold.
_ABOVE = 1e-6
# Whole-folder test: the 10th percentile of cohesion may sit this far below the mean threshold.
WHOLE_FOLDER_P10_MARGIN = 0.1
WHOLE_FOLDER_PERCENTILE = 10


@dataclass(frozen=True)
class CohesionParams:
    """The thresholds the unit gates need (see ``walk.GroupingParams``)."""

    parent: float  # a layout-overlapping pair counts as just above this
    layout_overlap: float  # mean cross edge correlation that marks the same building redrawn
    aspect_tolerance: float  # |log aspect| difference of compatible fingerprints


@dataclass(frozen=True)
class UnitSimilarity:
    """Pairwise cohesion and fingerprint compatibility of units."""

    cohesion: np.ndarray  # (m, m) mean cross embedding cosine, layout-raised
    compatible: np.ndarray  # (m, m) bool: fingerprints compatible and both have embeddings


def _nxm_compatible(nxm_sets: Sequence[set[tuple[int, int]]]) -> np.ndarray:
    """(m, m) bool: the units' NxM sizes overlap, or one of them names none."""
    values = sorted({v for s in nxm_sets for v in s})
    if not values:
        return np.ones((len(nxm_sets), len(nxm_sets)), dtype=bool)
    col = {v: k for k, v in enumerate(values)}
    incidence = np.zeros((len(nxm_sets), len(values)), dtype=np.float32)
    for u, s in enumerate(nxm_sets):
        for v in s:
            incidence[u, col[v]] = 1.0
    named = incidence.any(axis=1)
    share = (incidence @ incidence.T) > 0
    return share | ~named[:, None] | ~named[None, :]


def unit_similarity(
    units: Sequence[Sequence[int]],
    fm: FeatureMatrix,
    nxm: Sequence[tuple[int, int] | None],
    p: CohesionParams,
) -> UnitSimilarity:
    """Cohesion and fingerprint compatibility between ``units`` (lists of file indices).

    A unit's embedding is the mean of its members' (missing ones count as zero, so a unit with
    few embedded files is conservatively weak); the dot of two means is the mean cross cosine.
    """
    means = np.stack([fm.embedding[list(u)].mean(axis=0) for u in units])
    cohesion = means @ means.T
    edges = np.stack([fm.edge[list(u)].mean(axis=0) for u in units])
    overlap = (edges @ edges.T) >= p.layout_overlap
    cohesion = np.where(overlap, np.maximum(cohesion, p.parent + _ABOVE), cohesion)

    has = np.array([fm.has_embedding[list(u)].any() for u in units])
    aspect = np.array(
        [
            float(np.median(fm.log_aspect[known])) if len(known) else np.nan
            for known in ([i for i in u if fm.has_aspect[i]] for u in units)
        ]
    )
    with np.errstate(invalid="ignore"):  # NaN (unknown aspect) compares False
        aspect_ok = np.abs(aspect[:, None] - aspect[None, :]) < p.aspect_tolerance
    nxm_sets = [{size for i in u if (size := nxm[i]) is not None} for u in units]
    compatible = aspect_ok & _nxm_compatible(nxm_sets) & has[:, None] & has[None, :]
    np.fill_diagonal(compatible, True)
    return UnitSimilarity(cohesion, compatible)


def average_linkage(distance: np.ndarray, max_distance: float) -> np.ndarray:
    """Flat cluster labels of an (m, m) distance matrix: average linkage cut at ``max_distance``."""
    iu = np.triu_indices(len(distance), 1)
    tree = linkage(np.clip(distance[iu], 0.0, None), method="average")
    return fcluster(tree, max_distance, criterion="distance")


def gated_distance(sim: UnitSimilarity, allowed: np.ndarray | None = None) -> np.ndarray:
    """Cohesion distance (1 - cohesion), ``INCOMPATIBLE`` where the gate or ``allowed`` says no."""
    ok = sim.compatible if allowed is None else sim.compatible & allowed
    distance = np.where(ok, 1.0 - sim.cohesion, INCOMPATIBLE)
    np.fill_diagonal(distance, 0.0)
    return distance


def cohesive_partition(
    units: Sequence[Sequence[int]],
    fm: FeatureMatrix,
    nxm: Sequence[tuple[int, int] | None],
    p: CohesionParams,
    threshold: float,
) -> list[list[int]]:
    """Partition ``units`` (as positions) into cohesive, fingerprint-compatible clusters."""
    if len(units) < 2:
        return [list(range(len(units)))]
    labels = average_linkage(gated_distance(unit_similarity(units, fm, nxm, p)), 1.0 - threshold)
    return [np.flatnonzero(labels == lab).tolist() for lab in np.unique(labels)]


@dataclass(frozen=True)
class WholeFolderStats:
    """Cohesion statistics over every unit pair of a folder (for the decision log)."""

    units: int
    mean: float
    p10: float
    compatible: float  # share of unit pairs with compatible fingerprints

    def describe(self) -> str:
        return (
            f"cohesion mean {self.mean:.2f} p10 {self.p10:.2f} "
            f"fp-compatible {self.compatible:.2f} over {self.units} units"
        )


def whole_folder_cohesive(
    units: Sequence[Sequence[int]],
    fm: FeatureMatrix,
    nxm: Sequence[tuple[int, int] | None],
    p: CohesionParams,
    threshold: float,
    min_compatible: float,
) -> tuple[bool, WholeFolderStats]:
    """Whether every unit of a folder shares production and theme (E5 fix 0b, all-or-nothing).

    Every unit must have an embedding: a content-free unit cannot be shown to belong, so the
    whole-folder join is withheld (stricter than E5, which only required 90% of pairs).
    """
    sim = unit_similarity(units, fm, nxm, p)
    iu = np.triu_indices(len(units), 1)
    values = sim.cohesion[iu]
    stats = WholeFolderStats(
        units=len(units),
        mean=float(values.mean()),
        p10=float(np.percentile(values, WHOLE_FOLDER_PERCENTILE)),
        compatible=float(sim.compatible[iu].mean()),
    )
    all_embedded = all(fm.has_embedding[list(u)].any() for u in units)
    whole = (
        all_embedded
        and stats.mean >= threshold
        and stats.p10 >= threshold - WHOLE_FOLDER_P10_MARGIN
        and stats.compatible >= min_compatible
    )
    return whole, stats

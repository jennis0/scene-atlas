"""Unit-level content gates: theme cohesion and the production fingerprint (design/variant-grouping-algorithm.md §6.3).

A *unit* is a set of files already joined. At a meaningful parent folder, units join as
sub-groups only where content does not object: their **cohesion** (mean cross embedding cosine,
raised when their layouts overlap: the same building drawn again) is high, and their
**production fingerprint** (aspect ratio; ``NxM`` where both name one; a shared canvas, where
asked and both pixel sizes are known) is compatible. Cohesion only ever gates a join that the
folder structure or the names propose; it is never the reason for one.

A unit with no embedding, or no known aspect, is never compatible: the join is withheld. The
cohesion rules need ``params.embedding``; the walk only calls them when it is set.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from .evidence import FeatureMatrix
from .params import EmbeddingThresholds, GroupingParams

# Distance standing in for "incompatible" in average linkage (cosine distances are <= 2).
INCOMPATIBLE = 2.0
# Layout overlap raises a pair's cohesion to just above the parent threshold.
_ABOVE = 1e-6
# Whole-folder test: the 10th percentile of cohesion may sit this far below the mean threshold.
WHOLE_FOLDER_P10_MARGIN = 0.1
WHOLE_FOLDER_PERCENTILE = 10


def _embedding(params: GroupingParams) -> EmbeddingThresholds:
    if params.embedding is None:
        raise ValueError("cohesion needs the encoder's embedding thresholds")
    return params.embedding


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


def _median_aspects(units: Sequence[Sequence[int]], fm: FeatureMatrix) -> np.ndarray:
    """Each unit's median log aspect (NaN when none of its files has one)."""
    return np.array(
        [
            float(np.median(fm.log_aspect[known])) if len(known) else np.nan
            for known in ([i for i in u if fm.has_aspect[i]] for u in units)
        ]
    )


def canvas_compatible(
    units: Sequence[Sequence[int]], fm: FeatureMatrix, tolerance: float
) -> np.ndarray:
    """(m, m) bool: the units share a canvas, some pixel size of one within ``tolerance``
    (relative, in both dimensions) of some pixel size of the other. Renditions at several DPIs
    give a unit several sizes; a unit with no known size is compatible (no evidence either way).
    """
    sizes = [
        np.unique(fm.pixels[known], axis=0) if known else None
        for known in ([i for i in u if fm.has_pixels[i]] for u in units)
    ]
    m = len(units)
    out = np.ones((m, m), dtype=bool)
    for x in range(m):
        for y in range(x + 1, m):
            a, b = sizes[x], sizes[y]
            if a is None or b is None:
                continue
            relative = np.abs(a[:, None, :] - b[None, :, :]) / np.maximum(
                a[:, None, :], b[None, :, :]
            )
            out[x, y] = out[y, x] = bool((relative.max(axis=2) <= tolerance).any())
    return out


def _fingerprint(
    units: Sequence[Sequence[int]],
    fm: FeatureMatrix,
    nxm: Sequence[tuple[int, int] | None],
    params: GroupingParams,
    canvas: bool,
) -> np.ndarray:
    """(m, m) bool: the same aspect (both known) and the same ``NxM`` where both name one; with
    ``canvas``, also a shared canvas where both sizes are known."""
    aspect = _median_aspects(units, fm)
    with np.errstate(invalid="ignore"):  # NaN (unknown aspect) compares False
        same = np.abs(aspect[:, None] - aspect[None, :]) < params.aspect_tolerance
    same &= _nxm_compatible([{size for i in u if (size := nxm[i]) is not None} for u in units])
    if canvas:
        same &= canvas_compatible(units, fm, params.canvas_tolerance)
    return same


def production_compatible(
    units: Sequence[Sequence[int]],
    fm: FeatureMatrix,
    nxm: Sequence[tuple[int, int] | None],
    params: GroupingParams,
) -> np.ndarray:
    """(m, m) bool: one production (``_fingerprint`` with the canvas). Needs no embedding."""
    same = _fingerprint(units, fm, nxm, params, canvas=True)
    np.fill_diagonal(same, True)
    return same


def unit_similarity(
    units: Sequence[Sequence[int]],
    fm: FeatureMatrix,
    nxm: Sequence[tuple[int, int] | None],
    params: GroupingParams,
    canvas: bool = False,
) -> UnitSimilarity:
    """Cohesion and fingerprint compatibility between ``units`` (lists of file indices).

    A unit's embedding is the mean of its members' (missing ones count as zero, so a unit with
    few embedded files is conservatively weak); the dot of two means is the mean cross cosine.
    With ``canvas``, compatibility also needs a shared canvas (``canvas_compatible``).
    """
    means = np.stack([fm.embedding[list(u)].mean(axis=0) for u in units])
    cohesion = means @ means.T
    edges = np.stack([fm.edge[list(u)].mean(axis=0) for u in units])
    overlap = (edges @ edges.T) >= params.layout_overlap
    parent = _embedding(params).parent
    cohesion = np.where(overlap, np.maximum(cohesion, parent + _ABOVE), cohesion)

    has = np.array([fm.has_embedding[list(u)].any() for u in units])
    compatible = _fingerprint(units, fm, nxm, params, canvas) & has[:, None] & has[None, :]
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
    params: GroupingParams,
) -> list[list[int]]:
    """Partition ``units`` (as positions) into clusters cohesive at the shared-base threshold
    and fingerprint-compatible."""
    if len(units) < 2:
        return [list(range(len(units)))]
    sim = unit_similarity(units, fm, nxm, params)
    labels = average_linkage(gated_distance(sim), 1.0 - _embedding(params).shared_base)
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
    params: GroupingParams,
) -> tuple[bool, WholeFolderStats]:
    """Whether every unit of a folder shares production and theme (all or nothing): mean
    cohesion at the whole-folder threshold, its 10th percentile not far below, and enough unit
    pairs with compatible fingerprints.

    Every unit must have an embedding: a content-free unit cannot be shown to belong, so the
    whole-folder join is withheld.
    """
    sim = unit_similarity(units, fm, nxm, params)
    iu = np.triu_indices(len(units), 1)
    values = sim.cohesion[iu]
    stats = WholeFolderStats(
        units=len(units),
        mean=float(values.mean()),
        p10=float(np.percentile(values, WHOLE_FOLDER_PERCENTILE)),
        compatible=float(sim.compatible[iu].mean()),
    )
    threshold = _embedding(params).whole_folder
    all_embedded = all(fm.has_embedding[list(u)].any() for u in units)
    whole = (
        all_embedded
        and stats.mean >= threshold
        and stats.p10 >= threshold - WHOLE_FOLDER_P10_MARGIN
        and stats.compatible >= params.whole_folder_compatible
    )
    return whole, stats

"""Content evidence: per-file features, candidate pairs and pair signals (design §2 and §4).

Signals are kept separate, never fused into one score: a pHash rendition is *certain* evidence,
layout agreement needs the edge map **and** the embedding to agree. Candidate pairs are found
without holding a dense n × n matrix (CPU, numpy only):

- every pair within ``candidate_phash_bits`` of 256 pHash bits, by exact multi-index hashing
  (``phash_index``);
- each file's top-k neighbours by embedding cosine and by edge-map correlation, in row blocks,
  within its top-level folder (``candidate_pairs``);
- every pair inside small folders and small subtrees (the walk compares those exhaustively).

A file without a feature never takes part in a signal that needs it: the join is withheld, not
guessed (design §3, "merge-only"). Ported from scene-atlas-learning ``grouping/e5/content.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from .phash_index import radius_pairs, sorted_unique

PHASH_BYTES = 32  # 256-bit pHash (imagehash.phash(hash_size=16), MSB-first)
PHASH_BITS = PHASH_BYTES * 8
EDGE_DIM = 1024  # 32 × 32 edge-map layout descriptor

# Rows per block for the dense candidate searches: a block × n float32 matrix (40 MB at n = 10k).
_BLOCK_ROWS = 1024
# Rows per k-NN block: argpartition holds a block × n int64 array (200 MB at n = 50k).
_KNN_BLOCK_ROWS = 512
# Extra neighbours a k-NN row may keep when they tie with its k-th (identical renditions).
_KNN_TIES = 16
# Pairs per chunk when computing pair signals (bounds the gathered feature rows).
_PAIR_CHUNK = 65536
# Bits set per byte value, for Hamming distances on packed hashes.
_POPCOUNT = np.array([bin(b).count("1") for b in range(256)], dtype=np.uint16)


@dataclass(frozen=True)
class ContentFeatures:
    """Content features of one file; any field may be missing.

    - ``phash256``: 32 bytes, the 256-bit DCT pHash;
    - ``edge``: the 1024-float edge-map descriptor, z-scored (normalised to unit length here, so
      a dot product is a correlation; the stored z-scored vector and the unit vector both work);
    - ``log_aspect``: natural log of width / height;
    - ``embedding``: the active model's image embedding (normalised here).
    """

    phash256: bytes | None = None
    edge: np.ndarray | None = None
    log_aspect: float | None = None
    embedding: np.ndarray | None = None


def _unit_rows(rows: np.ndarray) -> np.ndarray:
    """Rows scaled to unit length (zero rows stay zero)."""
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    return rows / np.where(norms > 0, norms, 1.0)


class FeatureMatrix:
    """Features of all files as dense arrays aligned with the walk's file indices.

    Missing features are zero rows with a ``has_*`` flag False. Embeddings are optional as a
    whole (``use_embeddings``): without a calibration for the encoder they are not loaded.
    """

    def __init__(self, features: Sequence[ContentFeatures | None], use_embeddings: bool):
        n = len(features)
        self.n = n
        self.has_phash = np.zeros(n, dtype=bool)
        self.phash = np.zeros((n, PHASH_BYTES), dtype=np.uint8)
        self.has_edge = np.zeros(n, dtype=bool)
        edge = np.zeros((n, EDGE_DIM), dtype=np.float32)
        self.has_aspect = np.zeros(n, dtype=bool)
        self.log_aspect = np.zeros(n, dtype=np.float32)
        emb_rows: dict[int, np.ndarray] = {}
        for i, f in enumerate(features):
            if f is None:
                continue
            if f.phash256 is not None:
                if len(f.phash256) != PHASH_BYTES:
                    raise ValueError(f"phash256 must be {PHASH_BYTES} bytes, not {len(f.phash256)}")
                self.has_phash[i] = True
                self.phash[i] = np.frombuffer(f.phash256, dtype=np.uint8)
            if f.edge is not None:
                if f.edge.shape != (EDGE_DIM,):
                    raise ValueError(f"edge must have shape ({EDGE_DIM},), not {f.edge.shape}")
                self.has_edge[i] = True
                edge[i] = f.edge
            if f.log_aspect is not None and np.isfinite(f.log_aspect):
                self.has_aspect[i] = True
                self.log_aspect[i] = f.log_aspect
            if use_embeddings and f.embedding is not None:
                emb_rows[i] = np.asarray(f.embedding, dtype=np.float32).ravel()
        self.edge = _unit_rows(edge)
        self.has_embedding = np.zeros(n, dtype=bool)
        dims = {v.shape[0] for v in emb_rows.values()}
        if len(dims) > 1:
            raise ValueError(f"embeddings of different sizes: {sorted(dims)}")
        emb = np.zeros((n, dims.pop() if dims else 0), dtype=np.float32)
        for i, row in emb_rows.items():
            emb[i] = row
            self.has_embedding[i] = True
        self.embedding = _unit_rows(emb)

    @property
    def any_content(self) -> bool:
        """Whether any file has a feature a content rule could use."""
        return bool(self.has_phash.any() or self.has_edge.any() or self.has_embedding.any())


# ----------------------------------------------------------------------------- candidate pairs


def _phash_pairs(fm: FeatureMatrix, max_bits: int) -> np.ndarray:
    """All pairs (i < j) of hashed files within ``max_bits`` Hamming distance, over the whole
    input: renditions join across the tree (x1), so this search is never bucketed."""
    idx = np.flatnonzero(fm.has_phash)
    local = radius_pairs(fm.phash[idx], max_bits)
    return idx[local] if len(local) else np.zeros((0, 2), dtype=np.int64)


def _knn_pairs(
    rows: np.ndarray, has: np.ndarray, k: int, buckets: np.ndarray | None = None
) -> np.ndarray:
    """Each row's top-``k`` neighbours by dot product among rows with ``has``, as (i, j) pairs,
    searched within each bucket (all rows when ``buckets`` is None)."""
    idx = np.flatnonzero(has)
    if buckets is None:
        return _knn_in(rows, idx, k)
    idx = idx[np.argsort(buckets[idx], kind="stable")]  # group by bucket, file order within
    ids = buckets[idx]
    cuts = np.flatnonzero(ids[1:] != ids[:-1]) + 1
    out = [_knn_in(rows, part, k) for part in np.split(idx, cuts)]
    return np.concatenate(out) if out else np.zeros((0, 2), dtype=np.int64)


def _knn_in(rows: np.ndarray, idx: np.ndarray, k: int) -> np.ndarray:
    """Top-``k`` neighbour pairs among the rows ``idx``, in row blocks.

    Neighbours tied with the k-th are kept too (up to ``_KNN_TIES`` extra), so the result does
    not depend on how ties are broken: renditions often have identical embeddings. That also
    makes a bucket's neighbours a superset of the same-bucket part of a global search.
    """
    k = min(k, len(idx) - 1)
    if k < 1:
        return np.zeros((0, 2), dtype=np.int64)
    wide = min(k + _KNN_TIES, len(idx) - 1)
    sub = rows[idx]
    out = []
    for s in range(0, len(idx), _KNN_BLOCK_ROWS):
        sim = sub[s : s + _KNN_BLOCK_ROWS] @ sub.T
        sim[np.arange(sim.shape[0]), np.arange(s, s + sim.shape[0])] = -np.inf
        top = np.argpartition(-sim, wide - 1, axis=1)[:, :wide]
        values = np.take_along_axis(sim, top, axis=1)
        kth = -np.partition(-values, k - 1, axis=1)[:, k - 1 : k]
        src, col = np.nonzero(values >= kth)
        out.append(np.stack([idx[src + s], idx[top[src, col]]], axis=1))
    return np.concatenate(out)


def _all_pairs(groups: Iterable[Sequence[int]]) -> list[np.ndarray]:
    """Every pair within each group of file indices."""
    out = []
    for group in groups:
        if len(group) > 1:
            g = np.asarray(group, dtype=np.int64)
            a, b = np.triu_indices(len(g), 1)
            out.append(np.stack([g[a], g[b]], axis=1))
    return out


def candidate_pairs(
    fm: FeatureMatrix,
    exhaustive: Iterable[Sequence[int]],
    phash_bits: int,
    knn_embedding: int,
    knn_edge: int,
    buckets: np.ndarray | None = None,
) -> np.ndarray:
    """Unique candidate pairs (i < j), sorted: content neighbours plus ``exhaustive`` groups.

    ``buckets`` (an id per file) limits the embedding and edge neighbour searches to files of
    one bucket: the walk passes the top-level effective folder. That is exact for every join
    except the global suggestions: layout agreement, cohesion and gated shared bases only join
    at non-container folders, the root is always a container, so a pair whose files lie under
    different top-level folders can only join as a pHash rendition, and pHash candidates stay
    global. Each file's in-bucket top-k contains every same-bucket neighbour of its global
    top-k (ties aside).
    """
    parts = [
        _phash_pairs(fm, phash_bits),
        _knn_pairs(fm.embedding, fm.has_embedding, knn_embedding, buckets),
        _knn_pairs(fm.edge, fm.has_edge, knn_edge, buckets),
        *_all_pairs(exhaustive),
    ]
    pairs = np.concatenate(parts).astype(np.int64)
    lo, hi = np.minimum(pairs[:, 0], pairs[:, 1]), np.maximum(pairs[:, 0], pairs[:, 1])
    keep = lo != hi
    key = sorted_unique(lo[keep] * fm.n + hi[keep])
    return np.stack([key // fm.n, key % fm.n], axis=1)


# ----------------------------------------------------------------------------- pair signals


@dataclass(frozen=True)
class PairThresholds:
    """Thresholds of the two pair-level content rules (see ``walk.GroupingParams``)."""

    rendition_bits: int
    rendition_aspect: float
    agree_edge: float
    agree_embedding: float | None  # None: embedding rules are off, so no agreement
    agree_aspect: float


@dataclass(frozen=True)
class PairSignals:
    """Candidate pairs that are renditions or agree in layout (all other pairs are dropped)."""

    a: np.ndarray
    b: np.ndarray
    rendition: np.ndarray  # pHash within rendition_bits and the same aspect: certain
    agree: np.ndarray  # edge correlation and embedding cosine both high, same aspect: probable


def _rowwise_dot(x: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Dot products x[a] · x[b], chunked to bound memory."""
    out = np.empty(len(a), dtype=np.float32)
    for s in range(0, len(a), _PAIR_CHUNK):
        sa, sb = a[s : s + _PAIR_CHUNK], b[s : s + _PAIR_CHUNK]
        out[s : s + _PAIR_CHUNK] = np.einsum("ij,ij->i", x[sa], x[sb])
    return out


def _hamming(fm: FeatureMatrix, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """pHash Hamming distances of pairs."""
    return _POPCOUNT[np.bitwise_xor(fm.phash[a], fm.phash[b])].sum(axis=1)


def pair_signals(fm: FeatureMatrix, pairs: np.ndarray, t: PairThresholds) -> PairSignals:
    """Rendition and agreement flags for candidate pairs.

    Evaluated as a cascade (aspect, then pHash / embedding, then edge) so the expensive dot
    products only run on pairs that can still pass; the flags equal a full evaluation.
    """
    a, b = pairs[:, 0], pairs[:, 1]
    both_aspect = fm.has_aspect[a] & fm.has_aspect[b]
    aspect_d = np.abs(fm.log_aspect[a] - fm.log_aspect[b])

    rendition = both_aspect & (aspect_d < t.rendition_aspect) & fm.has_phash[a] & fm.has_phash[b]
    k = np.flatnonzero(rendition)
    rendition[k] = _hamming(fm, a[k], b[k]) <= t.rendition_bits

    agree = np.zeros(len(a), dtype=bool)
    if t.agree_embedding is not None:
        agree = (
            both_aspect
            & (aspect_d < t.agree_aspect)
            & fm.has_embedding[a]
            & fm.has_embedding[b]
            & fm.has_edge[a]
            & fm.has_edge[b]
        )
        k = np.flatnonzero(agree)
        agree[k] = _rowwise_dot(fm.embedding, a[k], b[k]) >= t.agree_embedding
        k = np.flatnonzero(agree)
        agree[k] = _rowwise_dot(fm.edge, a[k], b[k]) >= t.agree_edge

    keep = rendition | agree
    return PairSignals(a[keep], b[keep], rendition[keep], agree[keep])

"""Exact Hamming-radius search over 256-bit pHashes by multi-index hashing.

Split the 256 bits into ``r + 1`` chunks. Two hashes within ``r`` bits differ in at most ``r``
chunks, so by the pigeonhole principle they agree exactly on at least one: bucketing every hash
by (chunk index, chunk value) and comparing only hashes that share a bucket finds every pair,
and verifying each candidate with the full popcount keeps exactly the right ones (Norouzi,
Punjani & Fleet, "Fast search in Hamming space with multi-index hashing", CVPR 2012).

Near-identical images (blank or flat maps) can make one bucket hold most of the input. Members of
any bucket larger than ``MAX_BUCKET`` are compared by blocked brute force instead, once, so the
search is never slower than the brute force it replaces.
"""

from __future__ import annotations

import numpy as np

HASH_BITS = 256
# Above this many hashes sharing one chunk value, the bucket's members go to brute force. A
# bucket of s hashes makes s(s-1)/2 candidates per chunk; brute force costs O(s · m).
MAX_BUCKET = 256
# Rows per block of the brute-force search (a block × m float32 matrix).
_BLOCK_ROWS = 1024
# Candidate pairs verified per chunk of the popcount.
_VERIFY_CHUNK = 1 << 18
# Bits set per byte value.
_POPCOUNT = np.array([bin(b).count("1") for b in range(256)], dtype=np.uint16)


def sorted_unique(values: np.ndarray) -> np.ndarray:
    """Sorted distinct values of an int array. A sort and a diff: ``np.unique`` in numpy 2.x
    hashes, and is several times slower on the millions of pair keys deduplicated here."""
    if len(values) == 0:
        return values
    values = np.sort(values)
    return values[np.r_[True, values[1:] != values[:-1]]]


def hamming(hashes: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamming distances between packed hashes ``hashes[a]`` and ``hashes[b]``, chunked."""
    out = np.empty(len(a), dtype=np.uint16)
    for s in range(0, len(a), _VERIFY_CHUNK):
        x = np.bitwise_xor(hashes[a[s : s + _VERIFY_CHUNK]], hashes[b[s : s + _VERIFY_CHUNK]])
        out[s : s + _VERIFY_CHUNK] = _POPCOUNT[x].sum(axis=1)
    return out


def brute_force_pairs(hashes: np.ndarray, max_bits: int) -> np.ndarray:
    """All pairs (i < j) within ``max_bits``, by blocked ±1 matrix products (exact: integers
    up to 256 are exact in float32)."""
    m = len(hashes)
    if m < 2:
        return np.zeros((0, 2), dtype=np.int64)
    signs = np.unpackbits(hashes, axis=1).astype(np.float32) * 2.0 - 1.0
    need = HASH_BITS - 2 * max_bits  # dot of ±1 rows = 256 - 2 × Hamming
    out = []
    for s in range(0, m, _BLOCK_ROWS):
        r, c = np.nonzero(signs[s : s + _BLOCK_ROWS] @ signs.T >= need)
        r = r + s
        keep = r < c
        out.append(np.stack([r[keep], c[keep]], axis=1))
    return np.concatenate(out).astype(np.int64)


def _chunk_bounds(n_chunks: int) -> list[tuple[int, int]]:
    """``n_chunks`` contiguous bit ranges covering 256 bits, as equal as possible."""
    edges = np.linspace(0, HASH_BITS, n_chunks + 1).round().astype(int)
    return list(zip(edges[:-1].tolist(), edges[1:].tolist(), strict=True))


def _bucket_pairs(values: np.ndarray, oversized: np.ndarray) -> list[np.ndarray]:
    """Pair keys (i * m + j, i < j) of hashes sharing a chunk value; members of buckets over
    ``MAX_BUCKET`` are flagged in ``oversized`` instead."""
    m = len(values)
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    starts = np.flatnonzero(np.r_[True, sorted_values[1:] != sorted_values[:-1]])
    lengths = np.diff(np.r_[starts, m])
    big = lengths > MAX_BUCKET
    for start, length in zip(starts[big].tolist(), lengths[big].tolist(), strict=True):
        oversized[order[start : start + length]] = True
    keys = []
    for length in np.unique(lengths[(lengths >= 2) & ~big]).tolist():
        members = order[starts[lengths == length][:, None] + np.arange(length)]
        a, b = np.triu_indices(length, 1)
        i, j = members[:, a].ravel(), members[:, b].ravel()
        keys.append(np.minimum(i, j) * m + np.maximum(i, j))
    return keys


def radius_pairs(hashes: np.ndarray, max_bits: int) -> np.ndarray:
    """All pairs (i < j) of packed 32-byte hashes within ``max_bits`` Hamming distance, sorted.

    Exactly the pairs brute force finds, in sub-quadratic time on ordinary inputs.
    """
    m = len(hashes)
    if m < 2:
        return np.zeros((0, 2), dtype=np.int64)
    if max_bits >= HASH_BITS // 2:  # chunks would be too small to discriminate
        return brute_force_pairs(hashes, max_bits)
    bits = np.unpackbits(hashes, axis=1)
    oversized = np.zeros(m, dtype=bool)
    keys: list[np.ndarray] = []
    for start, end in _chunk_bounds(max_bits + 1):
        weights = np.left_shift(np.int64(1), np.arange(end - start, dtype=np.int64))
        keys += _bucket_pairs(bits[:, start:end].astype(np.int64) @ weights, oversized)
    found = []
    for chunk_keys in keys:  # verify before deduplicating: most candidates are chance hits
        lo, hi = chunk_keys // m, chunk_keys % m
        found.append(chunk_keys[hamming(hashes, lo, hi) <= max_bits])
    members = np.flatnonzero(oversized)
    if len(members) >= 2:
        local = brute_force_pairs(hashes[members], max_bits)
        lo, hi = members[local[:, 0]], members[local[:, 1]]
        found.append(np.minimum(lo, hi) * m + np.maximum(lo, hi))
    if not found:
        return np.zeros((0, 2), dtype=np.int64)
    key = sorted_unique(np.concatenate(found))
    return np.stack([key // m, key % m], axis=1)

"""Multi-index pHash search equals brute force exactly; bucketed k-NN keeps in-bucket pairs."""

import numpy as np
import pytest

from backend.app.services.variant_grouping import evidence as E
from backend.app.services.variant_grouping import phash_index as P


def as_set(pairs: np.ndarray) -> set[tuple[int, int]]:
    return {(int(a), int(b)) for a, b in pairs}


def reference(hashes: np.ndarray, max_bits: int) -> set[tuple[int, int]]:
    """Plain pairwise popcount: the definition."""
    ints = [int.from_bytes(h.tobytes(), "big") for h in hashes]
    return {
        (i, j)
        for i in range(len(ints))
        for j in range(i + 1, len(ints))
        if (ints[i] ^ ints[j]).bit_count() <= max_bits
    }


def flip(rng: np.random.Generator, base: np.ndarray, n_bits: int) -> np.ndarray:
    bits = np.unpackbits(base)
    bits[rng.choice(256, size=n_bits, replace=False)] ^= 1
    return np.packbits(bits)


def clustered(seed: int, clusters: int, size: int, spread: int) -> np.ndarray:
    """Near-duplicate clusters: each hash is its cluster's base with up to ``spread`` flips."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(clusters):
        base = rng.integers(0, 256, 32, dtype=np.uint8)
        out += [flip(rng, base, int(rng.integers(0, spread + 1))) for _ in range(size)]
    return np.stack(out)


@pytest.mark.parametrize("max_bits", [0, 3, 12, 20, 40])
def test_random_hashes(max_bits):
    hashes = np.random.default_rng(max_bits).integers(0, 256, (400, 32), dtype=np.uint8)
    hashes[200:] = hashes[:200]  # some exact duplicates too
    assert as_set(P.radius_pairs(hashes, max_bits)) == reference(hashes, max_bits)


@pytest.mark.parametrize("spread", [4, 20, 30])
def test_clustered_near_duplicates(spread):
    hashes = clustered(spread, clusters=30, size=12, spread=spread)
    assert as_set(P.radius_pairs(hashes, 20)) == reference(hashes, 20)


def test_degenerate_all_equal_hashes_fall_back_to_brute_force():
    """A bucket over MAX_BUCKET (blank maps all hashing alike) is searched by brute force."""
    rng = np.random.default_rng(7)
    same = np.zeros((P.MAX_BUCKET + 50, 32), dtype=np.uint8)
    others = rng.integers(0, 256, (60, 32), dtype=np.uint8)
    near = np.stack([flip(rng, same[0], k % 25) for k in range(40)])
    hashes = np.concatenate([same, others, near])
    pairs = as_set(P.radius_pairs(hashes, 20))
    assert pairs == reference(hashes, 20)
    assert len(pairs) > (P.MAX_BUCKET + 50) * (P.MAX_BUCKET + 49) // 2


def test_matches_blocked_brute_force():
    hashes = clustered(11, clusters=80, size=15, spread=24)  # 1200 hashes: > one block
    assert as_set(P.radius_pairs(hashes, 20)) == as_set(P.brute_force_pairs(hashes, 20))


def test_small_inputs():
    assert P.radius_pairs(np.zeros((0, 32), np.uint8), 20).shape == (0, 2)
    assert P.radius_pairs(np.zeros((1, 32), np.uint8), 20).shape == (0, 2)
    assert P.radius_pairs(np.zeros((2, 32), np.uint8), 20).tolist() == [[0, 1]]


class TestBucketedKnn:
    def test_in_bucket_top_k_keeps_every_same_bucket_global_neighbour(self):
        rng = np.random.default_rng(3)
        n, k = 600, 15
        rows = rng.normal(size=(n, 32)).astype(np.float32)
        rows /= np.linalg.norm(rows, axis=1, keepdims=True)
        has = np.ones(n, dtype=bool)
        has[::17] = False
        buckets = rng.integers(0, 7, n)
        global_pairs = E._knn_pairs(rows, has, k)
        bucketed = as_set(E._knn_pairs(rows, has, k, buckets))
        same_bucket = {(int(i), int(j)) for i, j in global_pairs if buckets[i] == buckets[j]}
        assert same_bucket <= bucketed
        assert all(buckets[i] == buckets[j] for i, j in bucketed)

    def test_candidate_pairs_keep_global_phash_pairs(self):
        """Renditions join across top-level folders, so pHash candidates are not bucketed."""
        h = bytes(32)
        feats = [E.ContentFeatures(phash256=h), E.ContentFeatures(phash256=h)]
        fm = E.FeatureMatrix(feats, use_embeddings=False)
        pairs = E.candidate_pairs(fm, [], 20, 5, 5, buckets=np.array([0, 1]))
        assert pairs.tolist() == [[0, 1]]

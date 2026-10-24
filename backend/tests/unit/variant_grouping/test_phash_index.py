"""Multi-index pHash search equals brute force exactly."""

import numpy as np
import pytest

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

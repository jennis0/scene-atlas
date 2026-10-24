"""Unit tests for variant_grouping.evidence and cohesion: features, pairs, signals, gates."""

import dataclasses

import numpy as np
import pytest

from backend.app.services.variant_grouping import EmbeddingThresholds, GroupingParams
from backend.app.services.variant_grouping import evidence as E
from backend.app.services.variant_grouping.cohesion import (
    cohesive_partition,
    unit_similarity,
    whole_folder_cohesive,
)
from backend.app.services.variant_grouping.evidence import ContentFeatures, FeatureMatrix

# rendition 12 bits / 0.02 aspect; agreement edge 0.7, embedding 0.7, aspect 0.05; parent 0.82
PARAMS = GroupingParams(embedding=EmbeddingThresholds())


def random_features(n: int, seed: int = 0, dim: int = 16) -> list[ContentFeatures]:
    rng = np.random.default_rng(seed)
    return [
        ContentFeatures(
            phash256=rng.integers(0, 256, 32, dtype=np.uint8).tobytes(),
            edge=rng.normal(size=E.EDGE_DIM),
            log_aspect=float(rng.normal(scale=0.2)),
            embedding=rng.normal(size=dim),
        )
        for _ in range(n)
    ]


def as_set(pairs: np.ndarray) -> set[tuple[int, int]]:
    return {(int(a), int(b)) for a, b in pairs}


class TestFeatureMatrix:
    def test_missing_features_are_flagged(self):
        fm = FeatureMatrix([None, ContentFeatures(log_aspect=0.1)], use_embeddings=True)
        assert not fm.has_phash.any() and not fm.has_edge.any() and not fm.has_embedding.any()
        assert fm.has_aspect.tolist() == [False, True]
        assert not fm.any_content

    def test_rows_are_unit_length(self):
        fm = FeatureMatrix(random_features(3), use_embeddings=True)
        np.testing.assert_allclose(np.linalg.norm(fm.edge, axis=1), 1.0, rtol=1e-5)
        np.testing.assert_allclose(np.linalg.norm(fm.embedding, axis=1), 1.0, rtol=1e-5)

    def test_embeddings_can_be_switched_off(self):
        fm = FeatureMatrix(random_features(3), use_embeddings=False)
        assert not fm.has_embedding.any()

    def test_bad_shapes_are_rejected(self):
        with pytest.raises(ValueError, match="phash256"):
            FeatureMatrix([ContentFeatures(phash256=b"x")], use_embeddings=True)
        with pytest.raises(ValueError, match="edge"):
            FeatureMatrix([ContentFeatures(edge=np.zeros(3))], use_embeddings=True)
        with pytest.raises(ValueError, match="different sizes"):
            FeatureMatrix(
                [ContentFeatures(embedding=np.ones(3)), ContentFeatures(embedding=np.ones(4))],
                use_embeddings=True,
            )


class TestCandidatePairs:
    def test_phash_pairs_are_candidates(self):
        """Every pair within the pHash budget is a candidate (the search is ``phash_index``)."""
        rng = np.random.default_rng(1)
        hashes = rng.integers(0, 256, (40, 32), dtype=np.uint8)
        hashes[20:] = hashes[:20]  # twins
        feats = [ContentFeatures(phash256=h.tobytes()) for h in hashes]
        fm = FeatureMatrix(feats, use_embeddings=False)
        pairs = as_set(E.candidate_pairs(fm, [], phash_bits=20, knn_embedding=0, knn_edge=0))
        assert {(k, k + 20) for k in range(20)} <= pairs

    def test_candidate_pairs_keep_global_phash_pairs(self):
        """Renditions join across top-level folders, so pHash candidates are not bucketed."""
        h = bytes(32)
        feats = [ContentFeatures(phash256=h), ContentFeatures(phash256=h)]
        fm = FeatureMatrix(feats, use_embeddings=False)
        pairs = E.candidate_pairs(fm, [], 20, 5, 5, buckets=np.array([0, 1]))
        assert pairs.tolist() == [[0, 1]]

    def test_knn_pairs_include_each_files_nearest(self):
        feats = random_features(30, seed=2)
        fm = FeatureMatrix(feats, use_embeddings=True)
        pairs = E.candidate_pairs(fm, [], phash_bits=0, knn_embedding=3, knn_edge=0)
        found = {tuple(p) for p in pairs.tolist()}
        sim = fm.embedding @ fm.embedding.T
        np.fill_diagonal(sim, -np.inf)
        for i in range(30):
            j = int(np.argmax(sim[i]))
            assert (min(i, j), max(i, j)) in found

    def test_files_without_a_feature_get_no_pairs_from_it(self):
        feats = random_features(5) + [ContentFeatures()]
        fm = FeatureMatrix(feats, use_embeddings=True)
        pairs = E.candidate_pairs(fm, [], phash_bits=256, knn_embedding=5, knn_edge=5)
        assert 5 not in pairs.ravel()

    def test_exhaustive_groups_and_dedup(self):
        fm = FeatureMatrix([ContentFeatures()] * 4, use_embeddings=True)
        pairs = E.candidate_pairs(fm, [[0, 1, 2], [2, 1]], 20, 5, 5)
        assert pairs.tolist() == [[0, 1], [0, 2], [1, 2]]

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


class TestPairSignals:
    def test_rendition_needs_close_hash_and_same_aspect(self):
        h = bytes(32)
        near = bytes([0b111] + [0] * 31)  # 3 bits away
        feats = [
            ContentFeatures(phash256=h, log_aspect=0.0),
            ContentFeatures(phash256=near, log_aspect=0.01),
            ContentFeatures(phash256=near, log_aspect=0.5),  # other aspect
            ContentFeatures(phash256=h),  # aspect unknown
        ]
        fm = FeatureMatrix(feats, use_embeddings=True)
        sig = E.pair_signals(fm, np.array([[0, 1], [0, 2], [0, 3]]), PARAMS)
        assert list(zip(sig.a.tolist(), sig.b.tolist(), strict=True)) == [(0, 1)]
        assert sig.rendition.tolist() == [True]

    def test_missing_hashes_are_never_renditions(self):
        """Two files without a pHash must not look identical (as zero hashes would)."""
        fm = FeatureMatrix([ContentFeatures(log_aspect=0.0)] * 2, use_embeddings=True)
        sig = E.pair_signals(fm, np.array([[0, 1]]), PARAMS)
        assert len(sig.a) == 0

    def test_agreement_needs_edge_and_embedding(self):
        edge = np.random.default_rng(3).normal(size=E.EDGE_DIM)
        emb = np.ones(8)
        other = np.random.default_rng(4).normal(size=E.EDGE_DIM)
        feats = [
            ContentFeatures(edge=edge, embedding=emb, log_aspect=0.0),
            ContentFeatures(edge=edge, embedding=emb, log_aspect=0.0),  # agrees
            ContentFeatures(edge=other, embedding=emb, log_aspect=0.0),  # other layout
            ContentFeatures(edge=edge, log_aspect=0.0),  # no embedding
        ]
        fm = FeatureMatrix(feats, use_embeddings=True)
        sig = E.pair_signals(fm, np.array([[0, 1], [0, 2], [0, 3]]), PARAMS)
        assert list(zip(sig.a.tolist(), sig.b.tolist(), strict=True)) == [(0, 1)]
        assert sig.agree.tolist() == [True] and sig.rendition.tolist() == [False]

    def test_agreement_off_without_embedding_calibration(self):
        edge = np.ones(E.EDGE_DIM)
        feats = [ContentFeatures(edge=edge, embedding=np.ones(4), log_aspect=0.0)] * 2
        fm = FeatureMatrix(feats, use_embeddings=True)
        assert len(E.pair_signals(fm, np.array([[0, 1]]), GroupingParams()).a) == 0


class TestCohesion:
    def themed(self, theme: int, layout: int, aspect: float = 0.0) -> ContentFeatures:
        rng_t = np.random.default_rng(100 + theme)
        rng_l = np.random.default_rng(200 + layout)
        emb = 0.95 * rng_t.normal(size=32) / 5.6 + 0.3 * rng_l.normal(size=32) / 5.6
        return ContentFeatures(
            edge=np.random.default_rng(300 + layout).normal(size=E.EDGE_DIM),
            embedding=emb,
            log_aspect=aspect,
        )

    def test_same_theme_is_cohesive_and_other_theme_is_not(self):
        fm = FeatureMatrix(
            [self.themed(0, 0), self.themed(0, 1), self.themed(1, 2)], use_embeddings=True
        )
        sim = unit_similarity([[0], [1], [2]], fm, [None] * 3, PARAMS)
        assert sim.cohesion[0, 1] > 0.82 > sim.cohesion[0, 2]
        parts = cohesive_partition([[0], [1], [2]], fm, [None] * 3, PARAMS)  # at shared_base
        assert sorted(map(sorted, parts)) == [[0, 1], [2]]

    def test_fingerprint_blocks_other_aspect_and_size(self):
        feats = [self.themed(0, 0), self.themed(0, 1, aspect=0.3), self.themed(0, 2)]
        fm = FeatureMatrix(feats, use_embeddings=True)
        nxm = [(20, 30), None, (12, 12)]
        sim = unit_similarity([[0], [1], [2]], fm, nxm, PARAMS)
        assert not sim.compatible[0, 1]  # aspect
        assert not sim.compatible[0, 2]  # NxM named by both, no overlap

    def test_unit_without_embedding_is_incompatible(self):
        feats = [self.themed(0, 0), ContentFeatures(log_aspect=0.0)]
        fm = FeatureMatrix(feats, use_embeddings=True)
        sim = unit_similarity([[0], [1]], fm, [None] * 2, PARAMS)
        assert not sim.compatible[0, 1]

    def test_layout_overlap_raises_cohesion(self):
        """The same building drawn again: overlapping edge maps pass the parent threshold."""
        edge = np.random.default_rng(9).normal(size=E.EDGE_DIM)
        rng = np.random.default_rng(10)
        feats = [
            ContentFeatures(edge=edge, embedding=rng.normal(size=32), log_aspect=0.0)
            for _ in range(2)
        ]
        fm = FeatureMatrix(feats, use_embeddings=True)
        sim = unit_similarity([[0], [1]], fm, [None] * 2, PARAMS)
        assert sim.cohesion[0, 1] > 0.82

    def test_whole_folder_needs_every_unit_embedded(self):
        feats = [self.themed(0, k) for k in range(4)]
        fm = FeatureMatrix(feats, use_embeddings=True)
        units = [[0], [1], [2], [3]]
        whole, stats = whole_folder_cohesive(units, fm, [None] * 4, PARAMS)
        assert whole and stats.mean > 0.8
        fm = FeatureMatrix([*feats[:3], ContentFeatures(log_aspect=0.0)], use_embeddings=True)
        anything = dataclasses.replace(PARAMS, whole_folder_compatible=0.0)
        whole, _ = whole_folder_cohesive(units, fm, [None] * 4, anything)
        assert not whole

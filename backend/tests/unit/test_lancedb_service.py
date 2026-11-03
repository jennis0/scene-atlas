"""Tests for LanceDBService using a real LanceDB instance (tmp_path).

These tests verify actual LanceDB behavior — query syntax, distance
conversion, upsert semantics, and deletion — rather than mocking the
service away.
"""

import numpy as np
import pytest

from backend.app.services.lancedb_service import LanceDBService


@pytest.fixture()
def svc(tmp_path):
    """Create a real LanceDBService backed by a temp directory."""
    service = LanceDBService(
        path=tmp_path / "lancedb",
        collection_name="test_embeddings",
        vector_size=32,
    )
    yield service
    service.close()


def _rand_vec(dim=32):
    """Return a normalised random float32 vector."""
    v = np.random.randn(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


class TestLanceDBServiceCRUD:
    def test_add_and_retrieve_single(self, svc):
        vec = _rand_vec()
        assert svc.add_image_embedding(
            1, vec, {"filename": "a.jpg", "author": "x", "base_name": "g"}
        )

        retrieved = svc.get_embedding(1)
        assert retrieved is not None
        cos_sim = np.dot(vec, retrieved) / (np.linalg.norm(vec) * np.linalg.norm(retrieved))
        assert cos_sim > 0.999

    def test_batch_add_and_retrieve(self, svc):
        items = [
            {
                "image_id": i,
                "embedding": _rand_vec(),
                "metadata": {"filename": f"{i}.jpg", "author": "a", "base_name": "g"},
            }
            for i in range(10)
        ]
        assert svc.batch_add_embeddings(items)

        result = svc.get_embeddings([0, 5, 9])
        assert set(result.keys()) == {0, 5, 9}

    def test_upsert_overwrites(self, svc):
        vec1 = _rand_vec()
        vec2 = _rand_vec()
        svc.add_image_embedding(1, vec1, {"filename": "old.jpg", "author": "a", "base_name": "g"})
        svc.add_image_embedding(1, vec2, {"filename": "new.jpg", "author": "a", "base_name": "g"})

        info = svc.get_collection_info()
        assert info["points_count"] == 1

        retrieved = svc.get_embedding(1)
        cos_sim = np.dot(vec2, retrieved) / (np.linalg.norm(vec2) * np.linalg.norm(retrieved))
        assert cos_sim > 0.999

    def test_delete_single(self, svc):
        svc.add_image_embedding(
            1, _rand_vec(), {"filename": "a.jpg", "author": "a", "base_name": "g"}
        )
        svc.add_image_embedding(
            2, _rand_vec(), {"filename": "b.jpg", "author": "a", "base_name": "g"}
        )

        assert svc.delete_image_embedding(1)
        assert svc.get_embedding(1) is None
        assert svc.get_embedding(2) is not None

    def test_delete_batch(self, svc):
        for i in range(5):
            svc.add_image_embedding(
                i, _rand_vec(), {"filename": f"{i}.jpg", "author": "a", "base_name": "g"}
            )

        assert svc.delete_embeddings([0, 1, 2])
        info = svc.get_collection_info()
        assert info["points_count"] == 2

    def test_delete_empty_list(self, svc):
        assert svc.delete_embeddings([]) is True


class TestLanceDBServiceSearch:
    def test_search_returns_results_with_scores(self, svc):
        target = _rand_vec()
        svc.add_image_embedding(
            1, target, {"filename": "target.jpg", "author": "a", "base_name": "g"}
        )
        for i in range(2, 11):
            svc.add_image_embedding(
                i, _rand_vec(), {"filename": f"{i}.jpg", "author": "a", "base_name": "g"}
            )

        results = svc.search_similar(target, limit=5)
        assert len(results) == 5
        # The target vector should be the best match (highest score)
        assert results[0]["image_id"] == 1
        assert results[0]["score"] > 0.99

    def test_search_score_threshold_filters(self, svc):
        target = _rand_vec()
        svc.add_image_embedding(1, target, {"filename": "a.jpg", "author": "a", "base_name": "g"})
        # Add a distant vector (negate = cosine similarity ~ -1, distance ~ 2)
        opposite = [-x for x in target]
        svc.add_image_embedding(2, opposite, {"filename": "b.jpg", "author": "a", "base_name": "g"})

        results = svc.search_similar(target, limit=10, score_threshold=0.5)
        ids = {r["image_id"] for r in results}
        assert 1 in ids
        assert 2 not in ids

    def test_search_empty_table(self, svc):
        results = svc.search_similar(_rand_vec(), limit=10)
        assert results == []

    def test_search_scores_are_similarity_not_distance(self, svc):
        vec = _rand_vec()
        svc.add_image_embedding(1, vec, {"filename": "a.jpg", "author": "a", "base_name": "g"})

        results = svc.search_similar(vec, limit=1)
        # Searching with the same vector should give score ~1.0
        assert results[0]["score"] > 0.99
        # Score should be similarity (0-1 range for normalised vectors), not distance
        assert 0.0 <= results[0]["score"] <= 1.01


class TestLanceDBServiceCollection:
    def test_collection_info(self, svc):
        for i in range(3):
            svc.add_image_embedding(
                i, _rand_vec(), {"filename": f"{i}.jpg", "author": "a", "base_name": "g"}
            )

        info = svc.get_collection_info()
        assert info["name"] == "test_embeddings"
        assert info["points_count"] == 3
        assert info["status"] == "ok"

    def test_delete_and_recreate_collection(self, svc):
        svc.add_image_embedding(
            1, _rand_vec(), {"filename": "a.jpg", "author": "a", "base_name": "g"}
        )
        svc.delete_collection()
        svc.ensure_collection()

        info = svc.get_collection_info()
        assert info["points_count"] == 0

    def test_delete_collection_by_name_rejects_active(self, svc):
        with pytest.raises(ValueError, match="Cannot delete the active"):
            svc.delete_collection_by_name("test_embeddings")

    def test_close_then_read_raises(self, svc):
        svc.add_image_embedding(
            1, _rand_vec(), {"filename": "a.jpg", "author": "a", "base_name": "g"}
        )
        svc.close()
        with pytest.raises(RuntimeError, match="closed"):
            svc.search_similar(_rand_vec())


class TestEnsureCollectionExisting:
    """Regression: lancedb>=0.30 ``list_tables()`` returns a response object, so a plain
    ``name in db.list_tables()`` check is always False and existing tables were never
    inspected."""

    def test_reopens_existing_table_without_losing_rows(self, tmp_path):
        first = LanceDBService(path=tmp_path / "db", collection_name="emb", vector_size=32)
        first.add_image_embedding(1, _rand_vec(), {"filename": "a", "author": "", "base_name": ""})
        first.close()

        second = LanceDBService(path=tmp_path / "db", collection_name="emb", vector_size=32)
        assert second.get_collection_info()["points_count"] == 1
        assert second.table_exists("emb")
        assert not second.table_exists("missing")
        second.close()

    def test_recreates_table_when_vector_size_changes(self, tmp_path):
        first = LanceDBService(path=tmp_path / "db", collection_name="emb", vector_size=32)
        first.add_image_embedding(1, _rand_vec(), {"filename": "a", "author": "", "base_name": ""})
        first.close()

        second = LanceDBService(path=tmp_path / "db", collection_name="emb", vector_size=64)
        second.add_image_embedding(
            2, _rand_vec(64), {"filename": "b", "author": "", "base_name": ""}
        )
        assert second.get_collection_info()["points_count"] == 1
        second.close()


class TestCacheBounds:
    def test_metadata_cache_stays_within_its_bound_over_many_writes(self, tmp_path, monkeypatch):
        """Each write is a table version whose manifest lists every fragment; lance's default
        session kept them all (1 GiB cap), growing quadratically through a bulk import."""
        import backend.app.services.lancedb_service as module

        bound = 256 * 1024
        monkeypatch.setattr(module, "_METADATA_CACHE_BYTES", bound)
        service = LanceDBService(tmp_path / "lancedb", "bounded", vector_size=8)
        try:
            for batch in range(150):  # unbounded, the cache reaches ~6.5 MB here
                service.batch_add_embeddings(
                    [
                        {"image_id": batch * 4 + i, "embedding": _rand_vec(8), "metadata": {}}
                        for i in range(4)
                    ]
                )
            assert service.session.size_bytes <= bound * 1.1
            assert len(service.get_embeddings(list(range(600)))) == 600
        finally:
            service.close()


class TestGetEmbeddingArrays:
    """Many ids are read by one streaming scan, few by filtered ``id IN`` queries."""

    def _fill(self, svc, n):
        vectors = {i: _rand_vec() for i in range(1, n + 1)}
        for start in range(1, n + 1, 50):  # several fragments, as an ingest writes them
            svc.batch_add_embeddings(
                [
                    {"image_id": i, "embedding": vectors[i], "metadata": {}}
                    for i in range(start, min(start + 50, n + 1))
                ]
            )
        return vectors

    @pytest.fixture()
    def paths(self, svc, monkeypatch):
        """Count scans and filtered queries; small thresholds so 300 rows exercise both."""
        import backend.app.services.lancedb_service as module

        monkeypatch.setattr(module, "_LOOKUP_MAX_IDS", 3)
        monkeypatch.setattr(module, "_SCAN_MIN_IDS", 1000)
        monkeypatch.setattr(module, "_SCAN_BATCH_ROWS", 64)  # batches cut across fragments
        calls = {"scan": 0, "filtered": 0}
        scan, lookup = module._scan_vectors, svc.get_embeddings

        def counted_scan(*args):
            calls["scan"] += 1
            return scan(*args)

        def counted_lookup(ids):
            calls["filtered"] += 1
            return lookup(ids)

        monkeypatch.setattr(module, "_scan_vectors", counted_scan)
        monkeypatch.setattr(svc, "get_embeddings", counted_lookup)
        return module, calls

    @pytest.mark.parametrize("wanted", [[5, 77, 299, 299, 1000], list(range(0, 400, 7))])
    def test_returns_float32_vectors_of_the_ids_found(self, svc, paths, wanted):
        vectors = self._fill(svc, 300)
        found = svc.get_embedding_arrays(wanted)
        assert sorted(found) == sorted({i for i in wanted if 1 <= i <= 300})
        for i, v in found.items():
            assert v.dtype == np.float32 and v.shape == (32,)
            assert np.array_equal(v, np.asarray(vectors[i], dtype=np.float32))

    def test_scans_only_for_a_large_share_of_the_table(self, svc, paths):
        _, calls = paths
        self._fill(svc, 300)
        svc.get_embedding_arrays(range(1, 21))  # 7% of the rows: filtered queries
        assert calls == {"scan": 0, "filtered": 7}
        svc.get_embedding_arrays(range(1, 41))  # 13%
        assert calls["scan"] == 1

    def test_scans_for_many_ids_whatever_the_share(self, svc, paths):
        module, calls = paths
        self._fill(svc, 300)
        module._SCAN_MIN_IDS = 10
        assert len(svc.get_embedding_arrays(range(1, 11))) == 10
        assert calls == {"scan": 1, "filtered": 0}

    def test_null_vectors_are_skipped_without_shifting_the_others(self, svc, paths):
        """``FixedSizeListArray.flatten`` drops null slots: rows after one would be cut at the
        wrong offsets."""
        import pyarrow as pa

        vectors = self._fill(svc, 300)
        n = 4
        svc._tbl.add(
            pa.table(
                {
                    "id": list(range(1000, 1000 + n)),
                    "vector": pa.array(
                        [None, *([float(k)] * 32 for k in range(1, n))],
                        type=pa.list_(pa.float32(), 32),
                    ),
                    "image_id": list(range(1000, 1000 + n)),
                    "filename": [""] * n,
                    "author": [""] * n,
                    "base_name": [""] * n,
                }
            )
        )
        _, calls = paths
        found = svc.get_embedding_arrays([*range(1, 301), *range(1000, 1000 + n)])
        assert calls["scan"] == 1
        assert 1000 not in found
        for k in range(1, n):
            assert np.array_equal(found[1000 + k], np.full(32, k, dtype=np.float32))
        assert all(np.array_equal(found[i], np.float32(vectors[i])) for i in vectors)

    def test_a_failing_scan_is_retried_then_falls_back_to_filtered_queries(
        self, svc, paths, monkeypatch
    ):
        module, calls = paths
        vectors = self._fill(svc, 300)
        failures = []

        def broken(*_args):
            failures.append(1)
            raise OSError("transient")

        monkeypatch.setattr(module, "_scan_vectors", broken)
        found = svc.get_embedding_arrays(range(1, 101))
        assert len(failures) == 2
        assert calls["filtered"] == 34  # ceil(100 / 3)
        assert sorted(found) == list(range(1, 101))
        assert all(np.array_equal(found[i], np.float32(vectors[i])) for i in found)

    def test_a_closed_service_raises_on_either_path(self, svc, paths):
        self._fill(svc, 300)
        svc.close()
        for ids in (range(1, 3), range(1, 200)):
            with pytest.raises(RuntimeError):
                svc.get_embedding_arrays(ids)

    def test_no_ids_reads_nothing(self, svc, paths):
        _, calls = paths
        assert svc.get_embedding_arrays([]) == {}
        assert calls == {"scan": 0, "filtered": 0}

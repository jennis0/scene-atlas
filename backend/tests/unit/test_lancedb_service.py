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

"""Tests for LanceDBService using a real LanceDB instance (tmp_path).

These tests verify actual LanceDB behavior — query syntax, distance
conversion, upsert semantics, and deletion — rather than mocking the
service away.
"""

from datetime import timedelta

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


def _vec(seed: int, dim: int = 32) -> list[float]:
    v = np.random.default_rng(seed).normal(size=dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


class TestCompaction:
    """The table is compacted once its fragment count grows with its size (a fragment per
    write slowed every later write and search), and superseded files don't pile up."""

    def _add(self, svc, start: int, n: int = 2):
        items = [
            {"image_id": i, "embedding": _vec(i), "metadata": {}} for i in range(start, start + n)
        ]
        assert svc.batch_add_embeddings(items)

    @staticmethod
    def _fragments(svc) -> int:
        return svc._tbl.stats()["fragment_stats"]["num_fragments"]

    @staticmethod
    def _disk(svc) -> int:
        return sum(p.stat().st_size for p in svc._path.rglob("*") if p.is_file())

    @pytest.fixture
    def due_at_four(self, monkeypatch):
        """Compaction due at 4 fragments, so tests needn't write 64 times."""
        from backend.app.services import lancedb_service as module

        monkeypatch.setattr(module, "compaction_due", lambda rows, fragments: fragments >= 4)
        return module

    def test_threshold_grows_with_the_table(self):
        from backend.app.services.lancedb_service import compaction_due

        assert not compaction_due(1_000, 63) and compaction_due(1_000, 64)
        assert not compaction_due(200_000, 96) and compaction_due(200_000, 97)

    def test_compacts_only_when_due_keeping_every_row(self, svc, due_at_four):
        for b in range(3):
            self._add(svc, b * 2)
        assert not svc.compact_if_fragmented()
        assert self._fragments(svc) == 3
        self._add(svc, 6)
        assert svc.compact_if_fragmented()
        assert self._fragments(svc) == 1
        stored = svc.get_embeddings(list(range(8)))
        assert sorted(stored) == list(range(8))
        assert np.allclose(stored[3], _vec(3))

    def test_decision_comes_from_the_table_so_it_survives_a_restart(self, svc, due_at_four):
        for b in range(4):
            self._add(svc, b * 2)
        reopened = LanceDBService(svc._path, svc.collection_name, vector_size=32)
        assert reopened.compact_if_fragmented()
        reopened.close()

    def test_superseded_files_are_cleaned_so_disk_stays_bounded(
        self, svc, due_at_four, monkeypatch
    ):
        monkeypatch.setattr(due_at_four, "CLEANUP_AFTER", timedelta(0))  # readers done
        sizes, versions = [], []
        for b in range(60):
            self._add(svc, b * 4, 4)
            if svc.compact_if_fragmented():
                sizes.append(self._disk(svc))
                versions.append(len(svc._tbl.list_versions()))
        assert len(sizes) >= 5
        # Without cleanup every compaction kept a full copy; now the table stays near its
        # own size and keeps a handful of versions
        assert max(versions) <= 2
        assert sizes[-1] < 2.5 * sizes[len(sizes) // 2]

    def test_a_reader_on_the_old_version_survives_a_compaction(self, svc, due_at_four):
        """With the real CLEANUP_AFTER, a search already running on the version before a
        compaction still finds its files."""
        import lancedb

        for b in range(4):
            self._add(svc, b * 2)
        old = lancedb.connect(str(svc._path)).open_table(svc.collection_name)
        assert svc.compact_if_fragmented()
        rows = old.search(_vec(3)).limit(8).to_list()
        assert sorted(r["image_id"] for r in rows) == list(range(8))

    def test_a_failed_compaction_never_raises_and_waits_before_trying_again(
        self, svc, due_at_four, monkeypatch, caplog
    ):
        for b in range(4):
            self._add(svc, b * 2)
        calls = []

        def broken(**kwargs):
            calls.append(kwargs)
            raise OSError("disk trouble")

        real_optimize = svc._tbl.optimize
        monkeypatch.setattr(svc._tbl, "optimize", broken)
        clock = [1000.0]
        monkeypatch.setattr(due_at_four.time, "monotonic", lambda: clock[0])
        assert svc.compact_if_fragmented() is False
        assert svc.compact_if_fragmented() is False  # within the back-off: not tried
        assert len(calls) == 1
        clock[0] += due_at_four.COMPACT_RETRY_AFTER + 1
        caplog.clear()
        assert svc.compact_if_fragmented() is False
        assert len(calls) == 2
        assert [r.exc_info for r in caplog.records if "failed again" in r.message] == [None]
        assert sorted(svc.get_embeddings(list(range(8)))) == list(range(8))
        monkeypatch.setattr(svc._tbl, "optimize", real_optimize)
        clock[0] += due_at_four.COMPACT_RETRY_AFTER + 1
        assert svc.compact_if_fragmented()  # and a success clears the back-off
        assert svc._compaction_failed_at is None

"""Unit test for DB batch failure isolation in _process_batch.

Verifies that a batch_save_to_database failure marks images as failed
but does not raise, so _run_group can continue to the next batch.
"""

from unittest.mock import patch

from backend.pipeline.ingestion import _process_batch


def _make_prepared_result(filename: str, status: str = "success") -> dict:
    """Create a minimal prepared result dict for _process_batch."""
    result = {
        "status": status,
        "original_image_path": f"/staging/{filename}",
        "image_data": {
            "name": filename,
            "filename": filename,
            "author": "Test",
            "storage_key": f"key_{filename}",
            "needs_review": True,
        },
        "qdrant_metadata": {"author": "Test"},
        "embedding": [0.1] * 512,
    }
    return result


class TestProcessBatchDbIsolation:
    @patch("backend.pipeline.ingestion.batch_save_to_qdrant")
    @patch("backend.pipeline.ingestion.batch_save_to_database")
    @patch("backend.pipeline.ingestion.batch_generate_clip_embeddings")
    def test_db_failure_marks_images_failed_not_raises(
        self, mock_clip, mock_db_save, mock_qdrant_save
    ):
        """When batch_save_to_database throws, images are marked failed but no exception propagates."""
        prepared = [_make_prepared_result("a.jpg"), _make_prepared_result("b.jpg")]

        # CLIP succeeds
        mock_clip.return_value = [[0.1] * 512, [0.2] * 512]
        # DB save throws
        mock_db_save.side_effect = Exception("disk full")

        # Should NOT raise
        results, batch_failed = _process_batch(prepared)

        assert batch_failed == 2
        assert all(r["status"] == "failed" for r in results)
        assert all("db_save" in r.get("error_info", {}).get("stage", "") for r in results)
        # Qdrant should NOT be called when DB save failed
        mock_qdrant_save.assert_not_called()

    @patch("backend.pipeline.ingestion.batch_save_to_qdrant")
    @patch("backend.pipeline.ingestion.batch_save_to_database")
    @patch("backend.pipeline.ingestion.batch_generate_clip_embeddings")
    def test_db_success_proceeds_normally(self, mock_clip, mock_db_save, mock_qdrant_save):
        """Normal path: DB save succeeds, Qdrant save is called."""
        prepared = [_make_prepared_result("a.jpg")]

        mock_clip.return_value = [[0.1] * 512]
        mock_db_save.return_value = [42]  # image IDs

        results, batch_failed = _process_batch(prepared)

        assert batch_failed == 0
        assert results[0]["status"] == "success"
        assert results[0].get("image_id") == 42
        mock_qdrant_save.assert_called_once()

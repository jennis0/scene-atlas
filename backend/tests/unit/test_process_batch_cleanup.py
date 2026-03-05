"""Tests for _process_batch orphan-file cleanup on DB save failure.

Verifies that when batch_save_to_database() raises, any files that were
already written to ImageStore / ThumbnailStore are deleted so they don't
become permanently orphaned.

Also verifies that the dedup (reuse) path does NOT delete files — those
storage_keys belong to existing Image rows and must be left alone.
"""

from unittest.mock import MagicMock, patch


def _make_prepared_result(
    storage_key: str,
    thumbnail_key: str,
    *,
    reuse_storage_key: str | None = None,
) -> dict:
    """Build a minimal 'success' result as returned by prepare_single_image."""
    image_data = {
        "filename": "test.jpg",
        "storage_key": storage_key,
        "thumbnail_key": thumbnail_key,
        "name": "Test",
        "author": "Author",
        "group_name": "TestGroup",
        "width": 100,
        "height": 100,
        "file_size": 1000,
        "content_hash": "abc123",
        "media_type": "image",
        "image_type": "battlemap",
        "gridded": None,
        "grid_width": None,
        "grid_height": None,
        "grid_type": None,
        "grid_confidence": None,
        "subgroup": None,
        "needs_review": False,
        "tags": [],
        "colors": [],
        "import_job_id": None,
    }
    if reuse_storage_key is not None:
        image_data["reuse_storage_key"] = reuse_storage_key

    result = {
        "status": "success",
        "image_data": image_data,
        "original_image_path": "/fake/test.jpg",
        "qdrant_metadata": {"filename": "test.jpg", "author": "Author", "base_name": "TestGroup"},
    }
    if reuse_storage_key is not None:
        result["reuse_embedding_from"] = 999  # pretend there's a source image id

    return result


class TestProcessBatchDbFailureCleanup:
    """When batch DB save fails, ImageStore/ThumbnailStore files must be cleaned up."""

    def test_storage_key_deleted_on_db_failure(self):
        """storage_key file is deleted from ImageStore when DB save raises."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [_make_prepared_result("abc.jpg", "abc_thumb.jpg")]

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                side_effect=Exception("DB write failed"),
            ),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
        ):
            results, failed, _warnings = _process_batch(prepared)

        mock_image_store.delete.assert_called_once_with("abc.jpg")
        assert failed == 1
        assert results[0]["status"] == "failed"

    def test_thumbnail_key_deleted_on_db_failure(self):
        """thumbnail_key file is deleted from ThumbnailStore when DB save raises."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [_make_prepared_result("abc.jpg", "abc_thumb.jpg")]

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                side_effect=Exception("DB write failed"),
            ),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
        ):
            _process_batch(prepared)

        mock_thumbnail_store.delete.assert_called_once_with("abc_thumb.jpg")

    def test_multiple_images_all_cleaned_up_on_db_failure(self):
        """All storage/thumbnail keys are cleaned up when DB save fails for a batch."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [
            _make_prepared_result("img1.jpg", "thumb1.jpg"),
            _make_prepared_result("img2.jpg", "thumb2.jpg"),
            _make_prepared_result("img3.jpg", "thumb3.jpg"),
        ]

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding] * 3,
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                side_effect=Exception("DB write failed"),
            ),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
        ):
            results, failed, _warnings = _process_batch(prepared)

        assert mock_image_store.delete.call_count == 3
        assert mock_thumbnail_store.delete.call_count == 3
        assert failed == 3
        assert all(r["status"] == "failed" for r in results)

    def test_no_cleanup_when_db_save_succeeds(self):
        """ImageStore.delete is NOT called when DB save succeeds."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [_make_prepared_result("abc.jpg", "abc_thumb.jpg")]

        mock_qdrant = MagicMock()
        mock_qdrant.get_embedding.return_value = None

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                return_value=[42],
            ),
            patch("backend.pipeline.ingestion.batch_save_to_qdrant"),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
            patch("backend.pipeline.ingestion.get_qdrant_service", return_value=mock_qdrant),
        ):
            results, failed, _warnings = _process_batch(prepared)

        mock_image_store.delete.assert_not_called()
        mock_thumbnail_store.delete.assert_not_called()
        assert failed == 0
        assert results[0]["status"] == "success"


class TestProcessBatchQdrantWarnings:
    """_process_batch generates warnings when batch_save_to_qdrant returns False."""

    def test_qdrant_failure_generates_warnings(self):
        """Each successfully-saved image gets a warning when Qdrant save fails."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [
            _make_prepared_result("img1.jpg", "thumb1.jpg"),
            _make_prepared_result("img2.jpg", "thumb2.jpg"),
        ]

        mock_qdrant = MagicMock()
        mock_qdrant.get_embedding.return_value = None

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding, dummy_embedding],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                return_value=[1, 2],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_qdrant",
                return_value=False,  # Qdrant save fails
            ),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
            patch("backend.pipeline.ingestion.get_qdrant_service", return_value=mock_qdrant),
        ):
            results, failed, warnings = _process_batch(prepared)

        # Both images succeed in DB but generate Qdrant warnings
        assert failed == 0
        assert all(r["status"] == "success" for r in results)
        assert len(warnings) == 2
        assert all(w["severity"] == "warning" for w in warnings)
        assert all(w["stage"] == "qdrant_save" for w in warnings)
        assert all("semantic search" in w["reason"] for w in warnings)

    def test_qdrant_success_generates_no_warnings(self):
        """No warnings are generated when Qdrant save succeeds."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [_make_prepared_result("img1.jpg", "thumb1.jpg")]

        mock_qdrant = MagicMock()
        mock_qdrant.get_embedding.return_value = None

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                return_value=[1],
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_qdrant",
                return_value=True,  # Qdrant save succeeds
            ),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
            patch("backend.pipeline.ingestion.get_qdrant_service", return_value=mock_qdrant),
        ):
            results, failed, warnings = _process_batch(prepared)

        assert failed == 0
        assert len(warnings) == 0


class TestProcessBatchReusePathGuard:
    """The reuse (dedup) path must NOT delete files when DB save fails.

    Reuse images share a storage_key with an existing Image row.  Deleting
    the file would orphan that existing row, not clean up a new orphan.
    """

    def test_reuse_image_storage_key_not_deleted_on_db_failure(self):
        """storage_key of a reuse image is left intact when DB save fails."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        # reuse_storage_key set → this is a duplicate pointing to an existing file
        prepared = [
            _make_prepared_result(
                "existing.jpg", "existing_thumb.jpg", reuse_storage_key="existing.jpg"
            )
        ]

        mock_qdrant = MagicMock()
        mock_qdrant.get_embedding.return_value = dummy_embedding  # reuse path retrieves from Qdrant

        with (
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
            patch("backend.pipeline.ingestion.get_qdrant_service", return_value=mock_qdrant),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                side_effect=Exception("DB write failed"),
            ),
        ):
            results, failed, _warnings = _process_batch(prepared)

        # File must NOT be deleted — it belongs to the existing image
        mock_image_store.delete.assert_not_called()
        mock_thumbnail_store.delete.assert_not_called()
        assert failed == 1
        assert results[0]["status"] == "failed"

    def test_mixed_batch_only_new_images_cleaned_on_db_failure(self):
        """In a mixed batch, only newly-copied files are deleted; reuse files are preserved."""
        from backend.pipeline.ingestion import _process_batch

        mock_image_store = MagicMock()
        mock_thumbnail_store = MagicMock()
        dummy_embedding = [0.1] * 512

        prepared = [
            _make_prepared_result("new1.jpg", "new1_thumb.jpg"),  # new — should be cleaned up
            _make_prepared_result(
                "existing.jpg", "existing_thumb.jpg", reuse_storage_key="existing.jpg"
            ),  # reuse — must NOT be cleaned up
            _make_prepared_result("new2.jpg", "new2_thumb.jpg"),  # new — should be cleaned up
        ]

        mock_qdrant = MagicMock()
        mock_qdrant.get_embedding.return_value = dummy_embedding

        with (
            patch(
                "backend.pipeline.ingestion.batch_generate_clip_embeddings",
                return_value=[dummy_embedding, dummy_embedding],
            ),
            patch("backend.pipeline.ingestion.get_qdrant_service", return_value=mock_qdrant),
            patch("backend.pipeline.ingestion.get_image_store", return_value=mock_image_store),
            patch(
                "backend.pipeline.ingestion.get_thumbnail_store",
                return_value=mock_thumbnail_store,
            ),
            patch(
                "backend.pipeline.ingestion.batch_save_to_database",
                side_effect=Exception("DB write failed"),
            ),
        ):
            results, failed, _warnings = _process_batch(prepared)

        # Only the two new images should have their files deleted
        deleted_storage_keys = {call.args[0] for call in mock_image_store.delete.call_args_list}
        assert deleted_storage_keys == {"new1.jpg", "new2.jpg"}
        assert "existing.jpg" not in deleted_storage_keys

        deleted_thumbnail_keys = {
            call.args[0] for call in mock_thumbnail_store.delete.call_args_list
        }
        assert deleted_thumbnail_keys == {"new1_thumb.jpg", "new2_thumb.jpg"}
        assert "existing_thumb.jpg" not in deleted_thumbnail_keys

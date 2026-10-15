"""Tests for backend.pipeline.error_classifier."""

import errno

from backend.pipeline.error_classifier import classify_ingest_error


class TestClassifyIngestError:
    """classify_ingest_error returns user-friendly reason, stage, and detail."""

    def test_pil_unidentified_image(self):
        # Simulate PIL.UnidentifiedImageError (which is a subclass of OSError,
        # but the type name is what we match on).  We create a plain exception
        # with the matching name pattern instead.
        exc = OSError("cannot identify image file 'bad.png'")
        result = classify_ingest_error(exc, stage="thumbnails")
        assert result["reason"] == "Image is corrupt or not a supported format"
        assert result["stage"] == "thumbnails"
        assert "cannot identify image file" in result["detail"]

    def test_decompression_bomb(self):
        exc = Exception("decompression bomb detected")
        result = classify_ingest_error(exc, stage="thumbnails")
        assert result["reason"] == "Image is too large to process safely (decompression bomb)"

    def test_cv2_could_not_read(self):
        exc = ValueError("Could not read image: /path/to/file.png")
        result = classify_ingest_error(exc, stage="colors")
        assert result["reason"] == "Image could not be read for processing"
        assert result["stage"] == "colors"

    def test_file_not_found(self):
        exc = FileNotFoundError("No such file: /foo/bar.png")
        result = classify_ingest_error(exc, stage="copy")
        assert result["reason"] == "File was not found"
        assert result["stage"] == "copy"

    def test_permission_error(self):
        exc = PermissionError("Permission denied: /foo/bar.png")
        result = classify_ingest_error(exc, stage="copy")
        assert result["reason"] == "File could not be accessed (permission denied)"

    def test_disk_full(self):
        exc = OSError(errno.ENOSPC, "No space left on device")
        result = classify_ingest_error(exc, stage="copy")
        assert result["reason"] == "Not enough disk space to process image"

    def test_memory_error(self):
        exc = MemoryError()
        result = classify_ingest_error(exc, stage="thumbnails")
        assert result["reason"] == "Image is too large to process (out of memory)"

    def test_embedding_stage_fallback(self):
        exc = RuntimeError("CLIP model failed somehow")
        result = classify_ingest_error(exc, stage="embedding")
        assert result["reason"] == "Failed to generate image embedding"

    def test_db_save_stage_fallback(self):
        exc = RuntimeError("database is locked")
        result = classify_ingest_error(exc, stage="db_save")
        assert result["reason"] == "Failed to save image to database"

    def test_vector_save_stage_fallback(self):
        exc = RuntimeError("vector db connection refused")
        result = classify_ingest_error(exc, stage="vector_save")
        assert result["reason"] == "Failed to save image embedding to search index"

    def test_generic_fallback(self):
        exc = RuntimeError("something unexpected")
        result = classify_ingest_error(exc, stage="colors")
        assert result["reason"] == "Processing failed during colors"
        assert result["stage"] == "colors"
        assert result["detail"] == "something unexpected"

    def test_detail_always_present(self):
        exc = ValueError("detailed error message")
        result = classify_ingest_error(exc, stage="parse")
        assert result["detail"] == "detailed error message"

    def test_stage_always_present(self):
        exc = Exception("test")
        for stage in [
            "parse",
            "copy",
            "thumbnails",
            "colors",
            "grid_detection",
            "embedding",
            "db_save",
            "vector_save",
        ]:
            result = classify_ingest_error(exc, stage=stage)
            assert result["stage"] == stage


class TestErrorKinds:
    """Each classified error carries a kind that tells the ingest worker how to react."""

    def test_corrupt_image_is_a_file_error(self):
        exc = OSError("cannot identify image file 'bad.png'")
        assert classify_ingest_error(exc, stage="decode")["kind"] == "file"

    def test_truncated_image_is_a_file_error(self):
        exc = OSError("image file is truncated (12 bytes not processed)")
        result = classify_ingest_error(exc, stage="decode")
        assert result["kind"] == "file"
        assert result["reason"] == "Image file is incomplete or truncated"

    def test_decompression_bomb_is_a_file_error(self):
        exc = Exception("decompression bomb detected")
        assert classify_ingest_error(exc, stage="decode")["kind"] == "file"

    def test_disk_full_is_a_system_error(self):
        exc = OSError(errno.ENOSPC, "No space left on device")
        assert classify_ingest_error(exc, stage="copy")["kind"] == "system"

    def test_missing_model_is_a_system_error(self):
        exc = RuntimeError("Embedding service unavailable: None")
        result = classify_ingest_error(exc, stage="embedding")
        assert result["kind"] == "system"
        assert result["reason"] == "No AI model is available"

    def test_system_unavailable_error_passes_reason_through(self):
        from backend.pipeline.error_classifier import SystemUnavailableError

        result = classify_ingest_error(SystemUnavailableError("Library drive missing"), "copy")
        assert result == {
            "reason": "Library drive missing",
            "kind": "system",
            "stage": "copy",
            "detail": "Library drive missing",
        }

    def test_database_locked_is_transient(self):
        import sqlite3

        from sqlalchemy.exc import OperationalError

        exc = OperationalError("INSERT ...", {}, sqlite3.OperationalError("database is locked"))
        assert classify_ingest_error(exc, stage="db_save")["kind"] == "transient"

    def test_memory_error_is_transient(self):
        assert classify_ingest_error(MemoryError(), stage="thumbnails")["kind"] == "transient"

    def test_unknown_errors_are_transient(self):
        """Unknown errors get bounded retries rather than failing on the first try."""
        result = classify_ingest_error(RuntimeError("weird"), stage="colors")
        assert result["kind"] == "transient"

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

"""Unit tests for pipeline task modules.

Tests color_extraction, image_processing, grid_detection, and embedding_generation.
Heavy infrastructure (CLIP, Qdrant) is mocked; real images are generated via fixtures.
"""

from unittest.mock import patch

import pytest
from PIL import Image as PILImage

# ---------------------------------------------------------------------------
# color_extraction
# ---------------------------------------------------------------------------


class TestRgbToHex:
    def test_black(self):
        from backend.pipeline.tasks.color_extraction import rgb_to_hex

        assert rgb_to_hex((0, 0, 0)) == "#000000"

    def test_white(self):
        from backend.pipeline.tasks.color_extraction import rgb_to_hex

        assert rgb_to_hex((255, 255, 255)) == "#ffffff"

    def test_red(self):
        from backend.pipeline.tasks.color_extraction import rgb_to_hex

        assert rgb_to_hex((255, 0, 0)) == "#ff0000"

    def test_arbitrary_color(self):
        from backend.pipeline.tasks.color_extraction import rgb_to_hex

        assert rgb_to_hex((26, 43, 60)) == "#1a2b3c"

    def test_float_values(self):
        from backend.pipeline.tasks.color_extraction import rgb_to_hex

        assert rgb_to_hex((26.7, 43.2, 60.9)) == "#1a2b3c"


class TestExtractDominantColors:
    def test_returns_correct_structure(self, tmp_path):
        from backend.pipeline.tasks.color_extraction import extract_dominant_colors

        # Create a multi-colored image so KMeans can find 3 clusters
        img = PILImage.new("RGB", (90, 90))
        for y in range(30):
            for x in range(90):
                img.putpixel((x, y), (200, 50, 50))  # red band
        for y in range(30, 60):
            for x in range(90):
                img.putpixel((x, y), (50, 200, 50))  # green band
        for y in range(60, 90):
            for x in range(90):
                img.putpixel((x, y), (50, 50, 200))  # blue band
        img_path = tmp_path / "multicolor.jpg"
        img.save(img_path, format="JPEG", quality=95)

        result = extract_dominant_colors(str(img_path), num_colors=3)

        assert isinstance(result, list)
        assert len(result) == 3
        for entry in result:
            assert "color_hex" in entry
            assert "percentage" in entry
            assert "color_order" in entry
            assert entry["color_hex"].startswith("#")
            assert len(entry["color_hex"]) == 7

    def test_percentages_sum_to_100(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.color_extraction import extract_dominant_colors

        img_path = tmp_path / "test.jpg"
        make_test_image(img_path, width=100, height=100)
        result = extract_dominant_colors(str(img_path), num_colors=3)
        total = sum(c["percentage"] for c in result)
        assert pytest.approx(total, abs=0.1) == 100.0

    def test_color_order_is_sequential(self, tmp_path):
        from backend.pipeline.tasks.color_extraction import extract_dominant_colors

        # Create a multi-colored image so KMeans can find 3 clusters
        img = PILImage.new("RGB", (90, 90))
        for y in range(30):
            for x in range(90):
                img.putpixel((x, y), (200, 50, 50))
        for y in range(30, 60):
            for x in range(90):
                img.putpixel((x, y), (50, 200, 50))
        for y in range(60, 90):
            for x in range(90):
                img.putpixel((x, y), (50, 50, 200))
        img_path = tmp_path / "multicolor.jpg"
        img.save(img_path, format="JPEG", quality=95)

        result = extract_dominant_colors(str(img_path), num_colors=3)
        orders = [c["color_order"] for c in result]
        assert orders == [1, 2, 3]

    def test_invalid_image_raises(self, tmp_path):
        from backend.pipeline.tasks.color_extraction import extract_dominant_colors

        bad_path = tmp_path / "nonexistent.jpg"
        with pytest.raises(ValueError, match="Could not read image"):
            extract_dominant_colors(str(bad_path), num_colors=3)

    def test_single_color_image(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.color_extraction import extract_dominant_colors

        img_path = tmp_path / "solid.jpg"
        make_test_image(img_path, width=50, height=50, color=(0, 128, 255))
        result = extract_dominant_colors(str(img_path), num_colors=1)
        assert len(result) == 1
        assert result[0]["percentage"] == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# image_processing
# ---------------------------------------------------------------------------


class TestGetImageDimensions:
    def test_returns_correct_dimensions(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.image_processing import get_image_dimensions

        img_path = tmp_path / "test.jpg"
        make_test_image(img_path, width=320, height=240)
        assert get_image_dimensions(str(img_path)) == (320, 240)

    def test_missing_file_raises(self, tmp_path):
        from backend.pipeline.tasks.image_processing import get_image_dimensions

        with pytest.raises((FileNotFoundError, OSError)):
            get_image_dimensions(str(tmp_path / "nope.jpg"))


class TestGetFileSize:
    def test_returns_positive_size(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.image_processing import get_file_size

        img_path = tmp_path / "test.jpg"
        make_test_image(img_path, width=50, height=50)
        size = get_file_size(str(img_path))
        assert size > 0
        assert size == img_path.stat().st_size

    def test_missing_file_raises(self, tmp_path):
        from backend.pipeline.tasks.image_processing import get_file_size

        with pytest.raises((FileNotFoundError, OSError)):
            get_file_size(str(tmp_path / "nope.jpg"))


class TestGeneratePreviewThumbnail:
    def test_generates_thumbnail_file(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.image_processing import generate_preview_thumbnail

        img_path = tmp_path / "src" / "image.jpg"
        make_test_image(img_path, width=200, height=200)
        staging = tmp_path / "staging"
        staging.mkdir()

        result = generate_preview_thumbnail(str(img_path), str(staging), "folder/image.jpg")
        assert result is not None
        assert result.endswith(".jpg")
        assert (staging / ".thumbs" / result).exists()

    def test_relative_path_slashes_replaced(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.image_processing import generate_preview_thumbnail

        img_path = tmp_path / "image.jpg"
        make_test_image(img_path)
        staging = tmp_path / "staging"
        staging.mkdir()

        result = generate_preview_thumbnail(str(img_path), str(staging), "a/b/c.png")
        assert result == "a__b__c.jpg"

    def test_returns_none_for_invalid_image(self, tmp_path):
        from backend.pipeline.tasks.image_processing import generate_preview_thumbnail

        staging = tmp_path / "staging"
        staging.mkdir()
        result = generate_preview_thumbnail(str(tmp_path / "nope.jpg"), str(staging), "x.jpg")
        assert result is None


class TestGenerateThumbnails:
    def test_generates_all_sizes(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.image_processing import generate_thumbnails

        img_path = tmp_path / "source.jpg"
        make_test_image(img_path, width=800, height=600)
        thumb_dir = tmp_path / "thumbs"
        thumb_dir.mkdir()

        with patch("backend.pipeline.tasks.image_processing.get_thumbnail_store") as mock_store:
            from backend.app.services.image_store import ImageStore

            store = ImageStore(thumb_dir)
            mock_store.return_value = store

            result = generate_thumbnails(str(img_path), "abc123")

        assert "keys" in result
        assert "dimensions" in result
        assert result["dimensions"] == (800, 600)
        assert "small" in result["keys"]
        assert "medium" in result["keys"]
        assert "large" in result["keys"]

        # Verify files were actually written
        for key in result["keys"].values():
            assert store.get_path(key).exists()


# ---------------------------------------------------------------------------
# grid_detection (task wrapper)
# ---------------------------------------------------------------------------


class TestDetectGridFromImage:
    def test_delegates_to_detector(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.grid_detection import detect_grid_from_image

        img_path = tmp_path / "map.jpg"
        make_test_image(img_path, width=400, height=400)

        mock_result = {
            "gridded": True,
            "grid_type": "square",
            "grid_width": 20,
            "grid_height": 20,
            "confidence": 0.85,
        }

        with patch("backend.pipeline.tasks.grid_detection.GridDetector") as MockDetector:
            instance = MockDetector.return_value
            instance.detect.return_value = mock_result

            result = detect_grid_from_image(str(img_path), 400, 400)

        assert result["gridded"] is True
        assert result["grid_type"] == "square"
        instance.detect.assert_called_once()

    def test_size_only_mode(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.grid_detection import detect_grid_from_image

        img_path = tmp_path / "map.jpg"
        make_test_image(img_path)

        mock_result = {
            "gridded": True,
            "grid_type": "square",
            "grid_width": 30,
            "grid_height": 20,
            "confidence": 0.9,
        }
        with patch("backend.pipeline.tasks.grid_detection.GridDetector") as MockDetector:
            instance = MockDetector.return_value
            instance.detect_size_only.return_value = mock_result

            result = detect_grid_from_image(str(img_path), 600, 400, size_only=True)

        instance.detect_size_only.assert_called_once()
        assert result["grid_width"] == 30

    def test_returns_safe_default_on_error(self, tmp_path):
        from backend.pipeline.tasks.grid_detection import detect_grid_from_image

        with patch("backend.pipeline.tasks.grid_detection.GridDetector") as MockDetector:
            MockDetector.side_effect = RuntimeError("boom")
            result = detect_grid_from_image(str(tmp_path / "nope.jpg"), 100, 100)

        assert result["gridded"] is None
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# embedding_generation
# ---------------------------------------------------------------------------


class TestGenerateClipEmbedding:
    def test_returns_embedding_via_mock(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.embedding_generation import generate_clip_embedding

        img_path = tmp_path / "img.jpg"
        make_test_image(img_path)
        dummy = [0.1] * 512

        with patch("backend.pipeline.tasks.embedding_generation.get_clip_service") as mock_clip:
            mock_clip.return_value.encode_image.return_value = dummy
            result = generate_clip_embedding(str(img_path))

        assert result == dummy
        assert len(result) == 512


class TestBatchGenerateClipEmbeddings:
    def test_processes_all_images(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.embedding_generation import batch_generate_clip_embeddings

        paths = []
        for i in range(5):
            p = tmp_path / f"img{i}.jpg"
            make_test_image(p)
            paths.append(str(p))

        dummy = [0.1] * 512
        with patch("backend.pipeline.tasks.embedding_generation.get_clip_service") as mock_clip:
            mock_clip.return_value.batch_encode_images.return_value = [dummy] * 3
            # batch_size=3 means two calls: [0:3] and [3:5]
            mock_clip.return_value.batch_encode_images.side_effect = [
                [dummy] * 3,
                [dummy] * 2,
            ]
            result = batch_generate_clip_embeddings(paths, batch_size=3)

        assert len(result) == 5
        assert mock_clip.return_value.batch_encode_images.call_count == 2

    def test_empty_list(self):
        from backend.pipeline.tasks.embedding_generation import batch_generate_clip_embeddings

        with patch("backend.pipeline.tasks.embedding_generation.get_clip_service"):
            result = batch_generate_clip_embeddings([], batch_size=10)

        assert result == []

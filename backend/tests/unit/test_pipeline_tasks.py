"""Unit tests for pipeline task modules.

Tests color_extraction, image_processing, grid_detection, and embedding_generation.
Heavy infrastructure (CLIP, LanceDB) is mocked; real images are generated via fixtures.
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


class TestWriteThumbnails:
    def test_writes_three_sizes_fitting_their_boxes(self, tmp_path):
        from backend.pipeline.tasks.image_processing import write_thumbnails

        img = PILImage.new("RGB", (1600, 1200), (10, 20, 30))
        result = write_thumbnails(img, "abc123", tmp_path / "out")

        assert set(result) == {"small", "medium", "large"}
        expected = {"small": (150, 112), "medium": (400, 300), "large": (800, 600)}
        for size_name, (key, path) in result.items():
            assert path.exists()
            assert key == path.name
            with PILImage.open(path) as thumb:
                assert thumb.format == "JPEG"
                assert thumb.size == expected[size_name]

    def test_keys_share_the_stem(self, tmp_path):
        from backend.pipeline.tasks.image_processing import write_thumbnails

        result = write_thumbnails(PILImage.new("RGB", (900, 900)), "stem42", tmp_path)
        assert sorted(key for key, _ in result.values()) == [
            "stem42_150x150.jpg",
            "stem42_400x400.jpg",
            "stem42_800x800.jpg",
        ]

    def test_small_images_are_not_upscaled(self, tmp_path):
        from backend.pipeline.tasks.image_processing import write_thumbnails

        result = write_thumbnails(PILImage.new("RGB", (120, 80)), "tiny", tmp_path)
        for _, path in result.values():
            with PILImage.open(path) as thumb:
                assert thumb.size[0] <= 120 and thumb.size[1] <= 80

    def test_rgba_and_palette_images_become_rgb(self, tmp_path):
        from backend.pipeline.tasks.image_processing import write_thumbnails

        for mode in ("RGBA", "P", "L"):
            result = write_thumbnails(PILImage.new(mode, (500, 500)), f"m{mode}", tmp_path)
            with PILImage.open(result["medium"][1]) as thumb:
                assert thumb.mode == "RGB"


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


# ---------------------------------------------------------------------------
# LanceDBService.get_embeddings (batch retrieval)
# ---------------------------------------------------------------------------


class TestGetEmbeddingsBatch:
    def test_returns_dict_of_vectors(self):
        """get_embeddings issues one query and returns image_id->vector mapping."""
        from unittest.mock import MagicMock

        from backend.app.services.lancedb_service import LanceDBService

        svc = LanceDBService.__new__(LanceDBService)
        import threading

        svc._lock = threading.RLock()
        mock_table = MagicMock()
        svc._table = mock_table
        svc.collection_name = "images"

        # LanceDB get_embeddings uses _table.search().where().limit().to_list()
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"image_id": 1, "vector": [0.1, 0.2]},
            {"image_id": 2, "vector": [0.3, 0.4]},
        ]

        result = svc.get_embeddings([1, 2])

        assert result == {1: [0.1, 0.2], 2: [0.3, 0.4]}

    def test_empty_input_returns_empty_dict(self):
        """get_embeddings([]) returns {} without calling the vector DB."""
        from unittest.mock import MagicMock

        from backend.app.services.lancedb_service import LanceDBService

        svc = LanceDBService.__new__(LanceDBService)
        import threading

        svc._lock = threading.RLock()
        mock_table = MagicMock()
        svc._table = mock_table
        svc.collection_name = "images"

        result = svc.get_embeddings([])

        mock_table.search.assert_not_called()
        assert result == {}

    def test_missing_ids_excluded(self):
        """IDs not found in the table are absent from the result."""
        from unittest.mock import MagicMock

        from backend.app.services.lancedb_service import LanceDBService

        svc = LanceDBService.__new__(LanceDBService)
        import threading

        svc._lock = threading.RLock()
        mock_table = MagicMock()
        svc._table = mock_table
        svc.collection_name = "images"

        # Only id=1 found; id=2 is missing from results
        mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
            {"image_id": 1, "vector": [0.1, 0.2]},
        ]

        result = svc.get_embeddings([1, 2])

        assert 1 in result
        assert 2 not in result

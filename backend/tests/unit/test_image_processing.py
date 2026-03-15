"""Tests for generate_thumbnails use_webp parameter."""


import pytest
from PIL import Image as PILImage

from backend.pipeline.tasks.image_processing import generate_thumbnails


@pytest.fixture
def sample_image(tmp_path) -> str:
    p = tmp_path / "sample.jpg"
    PILImage.new("RGB", (800, 600), color=(100, 150, 200)).save(str(p), format="JPEG")
    return str(p)


@pytest.fixture
def mock_thumb_store(tmp_path, monkeypatch):
    from backend.app.services.image_store import ImageStore

    store = ImageStore(tmp_path / "thumbs")
    monkeypatch.setattr(
        "backend.pipeline.tasks.image_processing.get_thumbnail_store",
        lambda: store,
    )
    return store


class TestThumbnailFormat:
    def test_jpeg_by_default(self, sample_image, mock_thumb_store):
        result = generate_thumbnails(sample_image, "abc123", use_webp=False)
        for key in result["keys"].values():
            assert key.endswith(".jpg"), f"Expected .jpg key, got {key}"

    def test_webp_when_flag_set(self, sample_image, mock_thumb_store):
        result = generate_thumbnails(sample_image, "abc123", use_webp=True)
        for key in result["keys"].values():
            assert key.endswith(".webp"), f"Expected .webp key, got {key}"

    def test_webp_files_are_actually_webp_format(self, sample_image, mock_thumb_store):
        result = generate_thumbnails(sample_image, "abc123", use_webp=True)
        for key in result["keys"].values():
            path = mock_thumb_store.get_path(key)
            with PILImage.open(path) as img:
                assert img.format == "WEBP", f"File at {path} is not WebP"

    def test_dimensions_returned_correctly(self, sample_image, mock_thumb_store):
        result = generate_thumbnails(sample_image, "abc123", use_webp=False)
        width, height = result["dimensions"]
        assert width == 800
        assert height == 600

    def test_rgba_image_thumbnails_preserve_alpha(self, tmp_path, mock_thumb_store):
        rgba_img = tmp_path / "rgba.png"
        PILImage.new("RGBA", (100, 100), (50, 100, 150, 200)).save(str(rgba_img))
        result = generate_thumbnails(str(rgba_img), "def456", use_webp=True)
        for key in result["keys"].values():
            path = mock_thumb_store.get_path(key)
            with PILImage.open(path) as img:
                assert img.mode == "RGBA"

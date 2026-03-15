"""Unit tests for WebP conversion helper and prepare_single_image integration."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image as PILImage

from backend.pipeline.pipeline_config import PipelineConfig
from backend.pipeline.tasks.webp_conversion import convert_to_webp, should_skip_conversion


def make_image(tmp_path, mode="RGB", ext=".png", filename=None) -> Path:
    """Create a minimal test image on disk."""
    name = filename or f"test{ext}"
    path = tmp_path / name
    img = PILImage.new(mode, (4, 4), 0)
    img.save(str(path))
    return path


def make_animated_gif(tmp_path) -> Path:
    path = tmp_path / "animated.gif"
    frames = [PILImage.new("P", (4, 4), i) for i in range(2)]
    frames[0].save(str(path), save_all=True, append_images=frames[1:], loop=0)
    return path


class TestShouldSkipConversion:
    def test_skip_video_mp4(self):
        assert should_skip_conversion(Path("clip.mp4")) is True

    def test_skip_video_webm(self):
        assert should_skip_conversion(Path("clip.webm")) is True

    def test_skip_already_webp(self):
        assert should_skip_conversion(Path("img.webp")) is True

    def test_skip_animated_gif(self, tmp_path):
        gif = make_animated_gif(tmp_path)
        assert should_skip_conversion(gif) is True

    def test_no_skip_static_gif(self, tmp_path):
        path = tmp_path / "static.gif"
        PILImage.new("P", (4, 4), 0).save(str(path))
        assert should_skip_conversion(path) is False

    def test_no_skip_png(self, tmp_path):
        p = make_image(tmp_path)
        assert should_skip_conversion(p) is False

    def test_no_skip_jpeg(self, tmp_path):
        p = tmp_path / "img.jpg"
        PILImage.new("RGB", (4, 4)).save(str(p), format="JPEG")
        assert should_skip_conversion(p) is False


class TestConvertToWebP:
    def test_rgb_png_converts(self, tmp_path):
        src = make_image(tmp_path, mode="RGB")
        result = convert_to_webp(src)
        assert result.suffix == ".webp"
        assert result.exists()
        with PILImage.open(result) as img:
            assert img.format == "WEBP"

    def test_rgba_preserves_alpha(self, tmp_path):
        src = make_image(tmp_path, mode="RGBA", ext=".png")
        result = convert_to_webp(src)
        with PILImage.open(result) as img:
            assert img.mode == "RGBA"

    def test_palette_with_transparency_becomes_rgba(self, tmp_path):
        img = PILImage.new("P", (4, 4), 0)
        img.info["transparency"] = 0
        src = tmp_path / "palette_trans.png"
        img.save(str(src))
        result = convert_to_webp(src)
        with PILImage.open(result) as out:
            assert out.mode == "RGBA"

    def test_palette_without_transparency_becomes_rgb(self, tmp_path):
        img = PILImage.new("P", (4, 4), 0)
        src = tmp_path / "palette.png"
        img.save(str(src))
        result = convert_to_webp(src)
        with PILImage.open(result) as out:
            assert out.mode == "RGB"

    def test_original_deleted_after_conversion(self, tmp_path):
        src = make_image(tmp_path)
        result = convert_to_webp(src)
        assert not src.exists()
        assert result.exists()

    def test_video_returned_unchanged(self, tmp_path):
        mp4 = tmp_path / "clip.mp4"
        mp4.write_bytes(b"fake")
        result = convert_to_webp(mp4)
        assert result == mp4
        assert mp4.exists()

    def test_already_webp_returned_unchanged(self, tmp_path):
        p = tmp_path / "img.webp"
        PILImage.new("RGB", (4, 4)).save(str(p), format="WEBP")
        result = convert_to_webp(p)
        assert result == p
        assert p.exists()

    def test_la_mode_becomes_rgba(self, tmp_path):
        # LA (greyscale+alpha) is converted to RGBA — WebP has no LA mode
        img = PILImage.new("LA", (4, 4), (128, 200))
        src = tmp_path / "la.png"
        img.save(str(src))
        result = convert_to_webp(src)
        with PILImage.open(result) as out:
            assert out.mode == "RGBA"

    def test_cmyk_becomes_rgb(self, tmp_path):
        img = PILImage.new("CMYK", (4, 4), (0, 0, 0, 0))
        src = tmp_path / "cmyk.jpg"
        img.save(str(src), format="JPEG")
        result = convert_to_webp(src)
        with PILImage.open(result) as out:
            assert out.mode == "RGB"


@pytest.fixture
def webp_cfg():
    return PipelineConfig(use_webp=True, enable_image_grid_detection=False)


class TestPrepareWithWebP:
    def test_stored_key_ends_in_webp(self, tmp_path, webp_cfg):
        from backend.app.services.image_store import ImageStore
        from backend.pipeline.prepare import prepare_single_image

        src = tmp_path / "map.png"
        PILImage.new("RGB", (100, 80)).save(str(src))

        image_store = ImageStore(tmp_path / "store")
        thumb_store = ImageStore(tmp_path / "thumbs")

        with (
            patch("backend.pipeline.prepare.get_image_store", return_value=image_store),
            patch(
                "backend.pipeline.tasks.image_processing.get_thumbnail_store",
                return_value=thumb_store,
            ),
            patch("backend.pipeline.prepare.pipeline_db"),
        ):
            result = prepare_single_image(
                str(src),
                metadata={
                    "group_name": "Test",
                    "author": None,
                    "name": "Test",
                    "subgroup": None,
                    "image_type": "battlemap",
                    "relative_path": "map.png",
                    "import_job_id": "job",
                    "content_hash": None,
                },
                pipeline_config=webp_cfg,
            )

        assert result["status"] == "success"
        assert result["image_data"]["storage_key"].endswith(".webp")
        if result["image_data"]["thumbnail_key"]:
            assert result["image_data"]["thumbnail_key"].endswith(".webp")

    def test_precomputed_hash_discarded_on_conversion(self, tmp_path, webp_cfg):
        from backend.app.services.image_store import ImageStore
        from backend.pipeline.prepare import prepare_single_image

        src = tmp_path / "map.jpg"
        PILImage.new("RGB", (100, 80)).save(str(src), format="JPEG")

        with open(src, "rb") as f:
            original_hash = hashlib.sha256(f.read()).hexdigest()

        image_store = ImageStore(tmp_path / "store")
        thumb_store = ImageStore(tmp_path / "thumbs")

        with (
            patch("backend.pipeline.prepare.get_image_store", return_value=image_store),
            patch(
                "backend.pipeline.tasks.image_processing.get_thumbnail_store",
                return_value=thumb_store,
            ),
            patch("backend.pipeline.prepare.pipeline_db"),
        ):
            result = prepare_single_image(
                str(src),
                metadata={
                    "group_name": "Test",
                    "author": None,
                    "name": "Test",
                    "subgroup": None,
                    "image_type": "battlemap",
                    "relative_path": "map.jpg",
                    "import_job_id": "job",
                    "content_hash": original_hash,  # Pre-computed from original
                },
                pipeline_config=webp_cfg,
            )

        stored_hash = result["image_data"]["content_hash"]
        assert stored_hash != original_hash, "Hash must be recomputed from WebP, not original"

    def test_colors_extracted_after_webp_conversion(self, tmp_path, webp_cfg):
        """Regression: _extract_colors must use image_path_obj (converted), not image_path (deleted)."""
        from backend.app.services.image_store import ImageStore
        from backend.pipeline.prepare import prepare_single_image

        src = tmp_path / "map.png"
        PILImage.new("RGB", (100, 80), color=(200, 100, 50)).save(str(src))

        image_store = ImageStore(tmp_path / "store")
        thumb_store = ImageStore(tmp_path / "thumbs")

        with (
            patch("backend.pipeline.prepare.get_image_store", return_value=image_store),
            patch(
                "backend.pipeline.tasks.image_processing.get_thumbnail_store",
                return_value=thumb_store,
            ),
            patch("backend.pipeline.prepare.pipeline_db"),
        ):
            result = prepare_single_image(
                str(src),
                metadata={
                    "group_name": "Test",
                    "author": None,
                    "name": "Test",
                    "subgroup": None,
                    "image_type": "battlemap",
                    "relative_path": "map.png",
                    "import_job_id": "job",
                    "content_hash": None,
                },
                pipeline_config=webp_cfg,
            )

        assert result["status"] == "success"
        assert isinstance(result["image_data"]["colors"], list)

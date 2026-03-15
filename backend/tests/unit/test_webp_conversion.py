"""Unit tests for WebP conversion helper."""

from pathlib import Path

from PIL import Image as PILImage

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

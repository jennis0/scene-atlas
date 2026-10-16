"""Storage-format conversion rules (design/ingest-redesign.md §10)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image as PILImage

from backend.pipeline.stored_format import StoredFormat, convert


def _write(path, mode="RGB", size=(40, 30), fmt=None, **kwargs):
    rng = np.random.default_rng(0)
    channels = {"RGB": 3, "RGBA": 4}[mode]
    pixels = rng.integers(0, 255, (size[1], size[0], channels), dtype=np.uint8)
    PILImage.fromarray(pixels, mode).save(path, fmt, **kwargs)
    return path


def test_original_never_converts(tmp_path):
    src = _write(tmp_path / "a.png")
    assert convert(src, tmp_path, "out", StoredFormat()) is None


def test_png_to_lossless_webp_is_pixel_identical(tmp_path):
    src = _write(tmp_path / "a.png", mode="RGBA")
    out = convert(src, tmp_path, "out", StoredFormat(format="webp"))
    assert out == tmp_path / "out.webp"
    with PILImage.open(src) as a, PILImage.open(out) as b:
        assert np.array_equal(np.asarray(a), np.asarray(b))


def test_jpeg_source_is_never_lossless_webp(tmp_path, monkeypatch):
    src = _write(tmp_path / "a.jpg")
    saved = {}
    original_save = PILImage.Image.save

    def spy(self, fp, format=None, **params):
        saved.update(params)
        return original_save(self, fp, format, **params)

    monkeypatch.setattr(PILImage.Image, "save", spy)
    convert(src, tmp_path, "out", StoredFormat(format="webp", quality=80, lossless=True))
    assert "lossless" not in saved
    assert saved["quality"] == 80
    assert saved["exact"] is True


@pytest.mark.parametrize(
    ("name", "mode", "target"),
    [
        ("same.jpg", "RGB", "jpeg"),  # already the target format
        ("same.png", "RGB", "png"),
        ("alpha.png", "RGBA", "jpeg"),  # would lose transparency
    ],
)
def test_kept_as_uploaded(tmp_path, name, mode, target):
    src = _write(tmp_path / name, mode=mode)
    assert convert(src, tmp_path, "out", StoredFormat(format=target)) is None
    assert not (tmp_path / "out.jpg").exists() and not (tmp_path / "out.png").exists()


def test_animated_image_kept_as_uploaded(tmp_path):
    frames = [PILImage.new("RGB", (8, 8), c) for c in ("red", "blue")]
    src = tmp_path / "anim.gif"
    frames[0].save(src, save_all=True, append_images=frames[1:])
    assert convert(src, tmp_path, "out", StoredFormat(format="webp")) is None


def test_too_large_for_webp_kept_as_uploaded(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.pipeline.stored_format.WEBP_MAX_DIM", 30)
    src = _write(tmp_path / "a.png", size=(40, 30))
    assert convert(src, tmp_path, "out", StoredFormat(format="webp")) is None


def test_icc_profile_is_preserved(tmp_path):
    from PIL import ImageCms

    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    src = _write(tmp_path / "a.png", icc_profile=icc)
    out = convert(src, tmp_path, "out", StoredFormat(format="jpeg"))
    with PILImage.open(out) as converted:
        assert converted.info.get("icc_profile") == icc


def test_failed_save_leaves_no_partial_file(tmp_path, monkeypatch):
    src = _write(tmp_path / "a.png")

    def boom(self, fp, *a, **k):
        open(fp, "wb").write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(PILImage.Image, "save", boom)
    with pytest.raises(OSError):
        convert(src, tmp_path, "out", StoredFormat(format="webp"))
    assert not (tmp_path / "out.webp").exists()

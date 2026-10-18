"""Tests for duplicate-detection hashes (backend/pipeline/image_hashes.py)."""

import numpy as np
from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

from backend.app.file_hash import file_sha256
from backend.pipeline.image_hashes import (
    hamming_distance,
    perceptual_hash,
    pixel_hash,
)


def _map_like(width=320, height=240, seed=7) -> Image.Image:
    """A textured image with structure, so perceptual hashes are meaningful."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (height // 20, width // 20, 3), dtype=np.uint8)
    img = Image.fromarray(base).resize((width, height), Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(img)
    draw.ellipse((60, 40, 200, 180), fill=(30, 90, 40))
    draw.rectangle((220, 120, 300, 220), fill=(150, 120, 80))
    return img


def _with_grid(img: Image.Image, cell: int = 32) -> Image.Image:
    gridded = img.copy()
    draw = ImageDraw.Draw(gridded)
    for x in range(0, img.width, cell):
        draw.line((x, 0, x, img.height), fill=(0, 0, 0), width=1)
    for y in range(0, img.height, cell):
        draw.line((0, y, img.width, y), fill=(0, 0, 0), width=1)
    return gridded


def _reopen(path):
    img = Image.open(path)
    img.load()
    return img


class TestPixelHash:
    def test_png_and_lossless_webp_match(self, tmp_path):
        img = _map_like()
        img.save(tmp_path / "a.png")
        img.save(tmp_path / "a.webp", lossless=True)
        assert pixel_hash(_reopen(tmp_path / "a.png")) == pixel_hash(_reopen(tmp_path / "a.webp"))

    def test_transparent_png_matches_its_lossless_webp(self, tmp_path):
        """Regression (Phase 0): libwebp rewrites colour under alpha=0 by default."""
        rgba = _map_like().convert("RGBA")
        pixels = np.array(rgba)
        pixels[:60, :, 3] = 0  # transparent band with arbitrary colour underneath
        pixels[:60, :, :3] = 200
        img = Image.fromarray(pixels, "RGBA")
        img.save(tmp_path / "a.png")
        img.save(tmp_path / "a.webp", lossless=True)  # exact=False: colour under alpha=0 changes
        assert pixel_hash(_reopen(tmp_path / "a.png")) == pixel_hash(_reopen(tmp_path / "a.webp"))

    def test_colour_under_transparency_is_ignored(self):
        a = np.zeros((10, 10, 4), dtype=np.uint8)
        b = a.copy()
        b[..., :3] = 123  # different invisible colour
        assert pixel_hash(Image.fromarray(a, "RGBA")) == pixel_hash(Image.fromarray(b, "RGBA"))

    def test_compression_and_metadata_dont_matter(self, tmp_path):
        img = _map_like()
        img.save(tmp_path / "a.png", compress_level=1)
        meta = PngInfo()
        meta.add_text("Author", "Someone")
        img.save(tmp_path / "b.png", compress_level=9, pnginfo=meta)
        assert file_sha256(tmp_path / "a.png") != file_sha256(tmp_path / "b.png")
        assert pixel_hash(_reopen(tmp_path / "a.png")) == pixel_hash(_reopen(tmp_path / "b.png"))

    def test_lossy_reencode_differs(self, tmp_path):
        img = _map_like()
        img.save(tmp_path / "a.jpg", quality=95)
        first = _reopen(tmp_path / "a.jpg")
        first.save(tmp_path / "b.jpg", quality=80)
        assert pixel_hash(first) != pixel_hash(_reopen(tmp_path / "b.jpg"))

    def test_gridded_and_gridless_differ(self):
        img = _map_like()
        assert pixel_hash(img) != pixel_hash(_with_grid(img))

    def test_decoding_is_deterministic(self, tmp_path):
        _map_like().save(tmp_path / "a.jpg", quality=90)
        assert pixel_hash(_reopen(tmp_path / "a.jpg")) == pixel_hash(_reopen(tmp_path / "a.jpg"))

    def test_mode_differences_with_same_pixels_match(self):
        rgb = _map_like()
        assert pixel_hash(rgb) == pixel_hash(rgb.convert("RGBA"))

    def test_size_is_part_of_the_hash(self):
        a = Image.new("RGB", (10, 20), (1, 2, 3))
        b = Image.new("RGB", (20, 10), (1, 2, 3))
        assert pixel_hash(a) != pixel_hash(b)

    def test_tall_images_hash_across_strips(self):
        tall = Image.new("RGB", (8, 1000), (5, 5, 5))
        changed = tall.copy()
        changed.putpixel((3, 999), (6, 5, 5))  # last strip only
        assert pixel_hash(tall) != pixel_hash(changed)

    def test_exif_orientation_is_applied(self, tmp_path):
        img = _map_like()
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90° CW on display
        img.save(tmp_path / "tagged.jpg", exif=exif, quality=100, subsampling=0)
        tagged = _reopen(tmp_path / "tagged.jpg")
        # Same stored pixels, no orientation tag: displays (and hashes) differently.
        untagged = Image.frombytes(tagged.mode, tagged.size, tagged.tobytes())
        assert pixel_hash(tagged) != pixel_hash(untagged)
        # ...and matches the explicitly rotated pixels.
        rotated = untagged.transpose(Image.Transpose.ROTATE_270)
        assert pixel_hash(tagged) == pixel_hash(rotated)


class TestPerceptualHash:
    def test_lossy_reencode_is_close(self, tmp_path):
        img = _map_like()
        img.save(tmp_path / "a.jpg", quality=60)
        assert (
            hamming_distance(perceptual_hash(img), perceptual_hash(_reopen(tmp_path / "a.jpg")))
            <= 4
        )

    def test_downscale_is_close(self):
        img = _map_like()
        small = img.resize((160, 120), Image.Resampling.LANCZOS)
        assert hamming_distance(perceptual_hash(img), perceptual_hash(small)) <= 4

    def test_grid_overlay_is_close(self):
        """Why pHash must never auto-skip: gridded/gridless variants look the same to it."""
        img = _map_like()
        assert hamming_distance(perceptual_hash(img), perceptual_hash(_with_grid(img))) <= 10

    def test_unrelated_images_are_far(self):
        a = perceptual_hash(_map_like(seed=1))
        b = perceptual_hash(_map_like(seed=2).transpose(Image.Transpose.FLIP_LEFT_RIGHT))
        assert hamming_distance(a, b) > 10

    def test_fits_in_signed_64_bits(self):
        value = perceptual_hash(_map_like())
        assert -(1 << 63) <= value < (1 << 63)

    def test_hamming_handles_sign(self):
        assert hamming_distance(-1, 0) == 64
        assert hamming_distance(-1, -1) == 0

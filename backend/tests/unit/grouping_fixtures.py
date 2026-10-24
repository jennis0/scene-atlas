"""Deterministic fixture images for the grouping-feature parity tests.

Built from integer arithmetic only (no RNG, no resampling, no trigonometry), so the
pixels are identical under any NumPy or Pillow version. That matters because the
expected values in ``grouping_features_reference.json`` were computed with the research
code (scene-atlas-learning's ``imagehash`` pHash and ``classbench/layout_features.py``)
in that project's environment; ``scripts/quality/grouping_feature_reference.py``
regenerates them.

Imports only NumPy and Pillow, so the reference script can load it from the research
environment.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PIL import Image


def _noise(height: int, width: int, seed: int, cell: int = 1) -> np.ndarray:
    """Integer hash noise in 0..255, constant over ``cell``×``cell`` blocks."""
    ys, xs = np.mgrid[0:height, 0:width].astype(np.uint32)
    ys //= np.uint32(cell)
    xs //= np.uint32(cell)
    h = (
        xs * np.uint32(374761393)
        + ys * np.uint32(668265263)
        + np.uint32((seed * 2654435761) & 0xFFFFFFFF)
    )
    h = (h ^ (h >> np.uint32(13))) * np.uint32(1274126177)
    return (h >> np.uint32(24)).astype(np.uint8)


def _map_like(width: int, height: int, seed: int) -> np.ndarray:
    """An RGB battlemap stand-in: blotchy terrain, rooms with dark walls, a road."""
    terrain = np.stack(
        [_noise(height, width, seed + k, cell=24) // 2 + 40 * k for k in range(3)], axis=-1
    ).astype(np.uint8)
    grain = _noise(height, width, seed + 7)[..., None] // 8
    pixels = (terrain.astype(np.int32) + grain).clip(0, 255).astype(np.uint8)
    for k in range(4):  # rooms: dark walls around a lighter floor
        top = (seed * 37 + k * 131) % max(1, height - height // 3)
        left = (seed * 53 + k * 197) % max(1, width - width // 3)
        bottom, right = top + height // 4, left + width // 4
        pixels[top:bottom, left:right] = (30, 28, 25)
        pixels[top + 4 : bottom - 4, left + 4 : right - 4] = (170 - 20 * k, 150, 120 + 10 * k)
    ys, xs = np.mgrid[0:height, 0:width]
    road = np.abs((xs * height - ys * width) // max(width, height)) < 6
    pixels[road] = (120, 100, 70)
    return pixels


def map_rgb() -> Image.Image:
    """800×600 RGB: the shape of a typical large thumbnail."""
    return Image.fromarray(_map_like(800, 600, seed=3), "RGB")


def map_portrait() -> Image.Image:
    """450×800 RGB, another layout."""
    return Image.fromarray(_map_like(450, 800, seed=11), "RGB")


def map_wide() -> Image.Image:
    """800×230 RGB: a long strip map."""
    return Image.fromarray(_map_like(800, 230, seed=19), "RGB")


def map_rgba() -> Image.Image:
    """640×480 RGBA: a transparent margin, a half-transparent band, coloured underneath."""
    rgb = _map_like(640, 480, seed=5)
    alpha = np.full((480, 640), 255, dtype=np.uint8)
    alpha[:, :80] = 0
    alpha[300:360, :] = 128
    rgb[:, :80] = (200, 0, 200)  # invisible colour under alpha 0
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def map_gray() -> Image.Image:
    """500×500 grayscale (L)."""
    return Image.fromarray(_map_like(500, 500, seed=23)[..., 1], "L")


def map_palette() -> Image.Image:
    """400×300 palette image with a transparent index (a GIF/PNG-8 export)."""
    index = (_map_like(400, 300, seed=29)[..., 0] // 16).astype(np.uint8)  # 16 colours
    image = Image.fromarray(index, "P")
    palette = []
    for k in range(256):
        palette += [(k * 16) % 256, (k * 40) % 256, 255 - (k * 16) % 256]
    image.putpalette(palette)
    image.info["transparency"] = 0
    return image


def map_cmyk() -> Image.Image:
    """300×200 CMYK (print exports)."""
    rgb = _map_like(300, 200, seed=31)
    k = np.full((200, 300, 1), 20, dtype=np.uint8)
    return Image.fromarray(np.concatenate([255 - rgb, k], axis=-1), "CMYK")


def tiny() -> Image.Image:
    """5×3 RGB: smaller than the 64×64 grid both features resample to."""
    pixels = (np.arange(45, dtype=np.uint16).reshape(3, 5, 3) * 37 % 256).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


FIXTURES: dict[str, Callable[[], Image.Image]] = {
    "map_rgb": map_rgb,
    "map_portrait": map_portrait,
    "map_wide": map_wide,
    "map_rgba": map_rgba,
    "map_gray": map_gray,
    "map_palette": map_palette,
    "map_cmyk": map_cmyk,
    "tiny": tiny,
}

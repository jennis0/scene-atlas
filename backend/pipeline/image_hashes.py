"""Content hashes used for duplicate detection (ADR-018, design/ingestion.md §6).

Three tiers:

1. ``file_sha256`` — exact bytes. Auto-skip.
2. ``pixel_hash``  — canonical decoded pixels. Catches the same image re-saved
   (PNG ↔ lossless WebP, different compression, edited metadata). Auto-skip.
3. ``perceptual_hash`` — 64-bit DCT pHash. Advisory only, never auto-skips:
   battlemap variants (gridded vs gridless, props) are near-duplicates by design.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

_FILE_CHUNK = 1024 * 1024
# Rows hashed per strip: bounds peak memory to ~strip_rows * width * 4 bytes
# instead of materialising a full RGBA copy of a 50+ megapixel map.
_PIXEL_STRIP_ROWS = 256


def file_sha256(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes, streamed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_FILE_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _oriented(image: Image.Image) -> Image.Image:
    """Apply EXIF orientation only when needed (exif_transpose always copies the image)."""
    orientation = image.getexif().get(0x0112, 1)
    return image if orientation in (None, 1) else ImageOps.exif_transpose(image)


_ALPHA_MODES = frozenset({"RGBA", "LA", "PA", "RGBa", "La"})


def _canonical_rgba_bytes(strip: Image.Image) -> bytes:
    """RGBA bytes with colour zeroed wherever alpha is 0.

    The colour under a fully transparent pixel is invisible, and encoders don't
    preserve it (libwebp rewrites it unless ``exact=True``), so it must not take
    part in the hash.
    """
    pixels = np.array(strip)  # writable copy, H×W×4
    pixels[pixels[..., 3] == 0, :3] = 0
    return pixels.tobytes()


def pixel_hash(image: Image.Image) -> str:
    """Hash of the image's canonical pixels: EXIF orientation applied, RGBA, metadata ignored.

    Identical pixels give identical hashes regardless of container format,
    compression level or metadata. Any visible pixel difference (including a
    lossy re-encode) gives a different hash, so this tier can't false-positive.

    SHA-256 rather than BLAKE2: with SHA-NI it hashed ~2× faster in the Phase 0
    benchmark.
    """
    oriented = _oriented(image)
    width, height = oriented.size
    may_have_alpha = oriented.mode in _ALPHA_MODES or "transparency" in oriented.info
    h = hashlib.sha256()
    h.update(f"rgba-v1:{width}x{height};".encode())
    for top in range(0, height, _PIXEL_STRIP_ROWS):
        bottom = min(top + _PIXEL_STRIP_ROWS, height)
        strip = oriented.crop((0, top, width, bottom))
        if strip.mode != "RGBA":
            strip = strip.convert("RGBA")
        h.update(_canonical_rgba_bytes(strip) if may_have_alpha else strip.tobytes())
    return h.hexdigest()


def perceptual_hash(image: Image.Image) -> int:
    """64-bit DCT perceptual hash, returned as a signed 64-bit int for SQLite storage.

    Grayscale → 32×32 → 2-D DCT → top-left 8×8 (minus DC) compared to its median.
    Pass a thumbnail-sized image; the hash only looks at low frequencies.
    """
    gray = _oriented(image).convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    dct = cv2.dct(np.asarray(gray, dtype=np.float32))
    low = dct[:8, :8].flatten()
    median = np.median(low[1:])  # exclude the DC term, which only encodes brightness
    bits = 0
    for value in low:
        bits = (bits << 1) | int(value > median)
    return bits - (1 << 64) if bits >= (1 << 63) else bits


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two (signed) 64-bit perceptual hashes."""
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()

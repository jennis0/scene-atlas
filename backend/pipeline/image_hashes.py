"""Content hashes used for duplicate detection (ADR-018, design/ingest-redesign.md §6).

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


def pixel_hash(image: Image.Image) -> str:
    """Hash of the image's canonical pixels: EXIF orientation applied, RGBA, metadata ignored.

    Identical pixels give identical hashes regardless of container format,
    compression level or metadata. Any pixel difference (including a lossy
    re-encode) gives a different hash, so this tier can't false-positive.
    """
    oriented = _oriented(image)
    width, height = oriented.size
    h = hashlib.blake2b(digest_size=32)
    h.update(f"rgba:{width}x{height};".encode())
    for top in range(0, height, _PIXEL_STRIP_ROWS):
        bottom = min(top + _PIXEL_STRIP_ROWS, height)
        strip = oriented.crop((0, top, width, bottom))
        if strip.mode != "RGBA":
            strip = strip.convert("RGBA")
        h.update(strip.tobytes())
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

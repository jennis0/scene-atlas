"""Per-image content features for variant grouping (ADR-028, design/variant-grouping.md §4).

Two features, each equal to what the research catalog computed, so the research's
thresholds transfer unchanged:

- ``phash256``: the 256-bit DCT perceptual hash ``imagehash.phash(hash_size=16)``.
  Renditions of one map (resized, re-encoded, gridded or not) are a few bits apart.
- ``edge_descriptor``: the layout descriptor of scene-atlas-learning's
  ``classbench/layout_features.py``: gradient magnitude on a 64×64 grayscale, pooled to
  32×32 and z-scored. Wall and terrain outlines survive recolouring (day/night, seasons).

Both read the large (800 px) thumbnail, as the research read its 800 px thumbnails.
Transparent pixels are flattened onto white first, as the research thumbnails were.
Parity with the research code is pinned by ``test_grouping_features.py`` against
references computed in the research environment.

Stored in ``image_grouping_features`` (one row per image, written at commit, replaced
by a linked refresh). Videos have no row; an image whose features couldn't be computed
has NULLs. ``load_grouping_features`` reads them back for an import's grouping phase.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import numpy as np
import scipy.fft
from PIL import Image
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.models.database import ImageGroupingFeatures
from backend.app.services.linked_files import chunks
from backend.app.timeutil import utcnow

from .image_hashes import _oriented

logger = logging.getLogger(__name__)

# Bump when either algorithm changes: rows of another version are ignored by
# load_grouping_features, as thresholds are calibrated per version.
GROUPING_FEATURES_VERSION = 1

PHASH256_BITS = 256
PHASH256_BYTES = PHASH256_BITS // 8
_PHASH_SIDE = 16  # hash_size: the top-left 16×16 DCT coefficients
_PHASH_RESAMPLED = 64  # hash_size × imagehash's highfreq_factor (4)

EDGE_SIDE = 32
EDGE_DIM = EDGE_SIDE * EDGE_SIDE
EDGE_DTYPE = np.dtype("<f2")  # little-endian float16, whatever the platform
EDGE_BYTES = EDGE_DIM * EDGE_DTYPE.itemsize
_EDGE_RESAMPLED = 2 * EDGE_SIDE

_WHITE = (255, 255, 255)


def _flattened_rgb(image: Image.Image) -> Image.Image:
    """EXIF-oriented RGB, with any transparency composited onto white.

    The research thumbnails (scene-atlas-learning ``preprocessing/thumbnails.py``) were
    made this way, so their features never saw the colour under transparent pixels.
    Scene Atlas keeps alpha in its thumbnails, so it is flattened here instead. Thumbnails
    carry no EXIF, so orientation only matters for other inputs (the research thumbnails
    weren't re-oriented either).
    """
    oriented = _oriented(image)
    if oriented.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in oriented.info:
        rgba = oriented.convert("RGBA")
        flat = Image.new("RGB", rgba.size, _WHITE)
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return oriented if oriented.mode == "RGB" else oriented.convert("RGB")


def _grayscale(image: Image.Image) -> Image.Image:
    """The input both features start from: RGB (as the research did), then L."""
    return _flattened_rgb(image).convert("L")


def _phash256(gray: Image.Image) -> bytes:
    small = gray.resize((_PHASH_RESAMPLED, _PHASH_RESAMPLED), Image.Resampling.LANCZOS)
    pixels = np.asarray(small, dtype=np.float64)
    # Unnormalised type-II DCT along columns then rows, as scipy.fftpack.dct in imagehash
    dct = np.asarray(scipy.fft.dct(scipy.fft.dct(pixels, axis=0), axis=1))
    low = dct[:_PHASH_SIDE, :_PHASH_SIDE]
    return np.packbits(low > np.median(low)).tobytes()  # median includes the DC term


def _zscore(values: np.ndarray) -> np.ndarray:
    flat = values.astype(np.float32).ravel()
    std = flat.std()
    return (flat - flat.mean()) / std if std > 1e-6 else np.zeros_like(flat)


def _edge_descriptor(gray: Image.Image) -> np.ndarray:
    small = gray.resize((_EDGE_RESAMPLED, _EDGE_RESAMPLED), Image.Resampling.BILINEAR)
    a = np.asarray(small, dtype=np.float32)
    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1] = a[:, 2:] - a[:, :-2]  # central differences; the borders stay 0
    gy[1:-1, :] = a[2:, :] - a[:-2, :]
    magnitude = np.hypot(gx, gy).reshape(EDGE_SIDE, 2, EDGE_SIDE, 2).mean(axis=(1, 3))
    return _zscore(magnitude).astype(EDGE_DTYPE)


def phash256(image: Image.Image) -> bytes:
    """256-bit DCT perceptual hash, 32 bytes, bits MSB-first in row-major order.

    Bit-identical to ``imagehash.phash(image.convert("RGB"), hash_size=16)`` for opaque
    images (``bytes.hex()`` is imagehash's ``str()``): grayscale, LANCZOS to 64×64, 2-D
    DCT, top-left 16×16, each coefficient compared with their median.
    """
    return _phash256(_grayscale(image))


def edge_descriptor(image: Image.Image) -> np.ndarray:
    """The research layout descriptor: 1024 float16 (32×32 row-major), z-scored.

    Grayscale, BILINEAR to 64×64, central-difference gradient magnitude, mean-pooled
    2×2 to 32×32, then z-scored (mean 0, population std 1; all zeros for a flat image).
    Because it is z-scored, ``a @ b / 1024`` is the Pearson correlation of two
    descriptors' edge maps (up to float16 rounding); the research compares them by that
    correlation, computed as the dot product of ``d / 32`` unit vectors.
    """
    return _edge_descriptor(_grayscale(image))


def phash256_distance(a: bytes, b: bytes) -> int:
    """Hamming distance between two ``phash256`` values (0–256)."""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).bit_count()


@dataclass(frozen=True)
class GroupingFeatures:
    """One image's features as computed; either may be None if it couldn't be."""

    phash256: bytes | None
    edge: np.ndarray | None  # (EDGE_DIM,) EDGE_DTYPE


def _guarded[T](
    name: str, compute: Callable[[Image.Image], T], image: Image.Image, label: str
) -> T | None:
    try:
        return compute(image)
    except Exception:
        logger.warning("Grouping %s failed for %s", name, label, exc_info=True)
        return None


def compute_grouping_features(image: Image.Image, label: str = "an image") -> GroupingFeatures:
    """Both features of a (large thumbnail) image. Never raises: a feature that fails is
    logged and left None, and the image groups by its other evidence (names, folders)."""
    gray = _guarded("input", _grayscale, image, label)
    if gray is None:
        return GroupingFeatures(None, None)
    return GroupingFeatures(
        _guarded("phash256", _phash256, gray, label),
        _guarded("edge descriptor", _edge_descriptor, gray, label),
    )


# Storage


def store_grouping_features(db: Session, features: Mapping[int, GroupingFeatures | None]) -> None:
    """Write each image's features row, replacing any it had. ``None`` (a video) leaves
    the image with no row. Runs in the caller's transaction.

    Replacing rather than inserting also clears a row left behind for a reused image id
    (SQLite reuses the highest rowid after a delete).
    """
    image_ids = sorted(features)
    now = utcnow()
    rows = [
        {
            "image_id": image_id,
            "version": GROUPING_FEATURES_VERSION,
            "phash256": f.phash256,
            "edge": f.edge.astype(EDGE_DTYPE).tobytes() if f.edge is not None else None,
            "computed_at": now,
        }
        for image_id in image_ids
        if (f := features[image_id]) is not None
    ]
    for chunk in chunks(image_ids):
        db.execute(delete(ImageGroupingFeatures).where(ImageGroupingFeatures.image_id.in_(chunk)))
    if rows:
        db.execute(insert(ImageGroupingFeatures), rows)


@dataclass(frozen=True)
class GroupingFeatureRow:
    """A stored features row, decoded. A feature is None when it couldn't be computed."""

    image_id: int
    version: int
    phash256: bytes | None  # PHASH256_BYTES, compare with phash256_distance
    edge: np.ndarray | None  # (EDGE_DIM,) float16, read-only; z-scored: a @ b / 1024 = r


def _checked(image_id: int, blob: bytes | None, size: int, what: str) -> bytes | None:
    if blob is not None and len(blob) != size:
        logger.warning("Ignoring a malformed %s for image %s", what, image_id)
        return None
    return blob


def load_grouping_features(db: Session, image_ids: Iterable[int]) -> dict[int, GroupingFeatureRow]:
    """image id → its decoded features row, for rows of the current version.

    Images without a row (videos, images imported before migration 029) and rows of
    another version are absent: grouping treats them as having no content evidence.
    """
    ids = sorted(set(image_ids))
    table = ImageGroupingFeatures
    found: dict[int, GroupingFeatureRow] = {}
    for chunk in chunks(ids):
        rows = db.execute(
            select(table.image_id, table.version, table.phash256, table.edge).where(
                table.image_id.in_(chunk), table.version == GROUPING_FEATURES_VERSION
            )
        )
        for image_id, version, phash, edge in rows:
            phash = _checked(image_id, phash, PHASH256_BYTES, "phash256")
            edge = _checked(image_id, edge, EDGE_BYTES, "edge descriptor")
            found[image_id] = GroupingFeatureRow(
                image_id,
                version,
                bytes(phash) if phash is not None else None,
                np.frombuffer(edge, dtype=EDGE_DTYPE) if edge is not None else None,
            )
    return found

"""Process one claimed batch of import items (ADR-018, design/ingestion.md §5.3).

    prepare (prepare pool) → embed (one batch) → commit (one BEGIN IMMEDIATE
    transaction) → vectors (LanceDB, after commit) → staging cleanup

Auto items (design §5.6) stop prepare after decoding: their type, and so whether grid
detection runs, comes from the image-type head, which reads the embedding. They are
sorted after embedding; maps and scenes are then finished on the prepare pool, the rest
are skipped with a preview kept for review.

A file is either fully in the library (row, stored file, thumbnails) or not at
all. Prepare writes the stored original and thumbnails as temp files next to
their destinations (``<store>/.incoming/``); the commit renames them into place
inside the transaction and deletes them again if the transaction fails. Vectors
are written after the commit; a failure there is repaired by
``vector_reconcile``.

Linked items (design/library-setup.md §4.4) are read where they are, through the linked
folder, and never copied: the image's original is the file itself (``storage_key``
NULL). Each outcome is written back to the file's ``source_files`` row. A linked item
whose file already is an image's is a refresh (§4.5, ``linked_refresh``): it goes through
the same steps and updates that image in place.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from PIL import Image as PILImage
from sqlalchemy import delete

from backend.app.config import settings
from backend.app.file_hash import file_sha256
from backend.app.models import Color, Image, ImageGroup, ImportGroup, ImportItem, Tag
from backend.app.models.database import GRID_FIELDS, GRID_SOURCE_DETECTOR, GRID_SOURCE_FILENAME
from backend.app.services import (
    get_image_store,
    get_lancedb_service,
    get_thumbnail_store,
)
from backend.app.services import ingest_state as st
from backend.app.services.deletion_service import PendingFileDeletes
from backend.app.services.image_parser import build_search_text
from backend.app.services.image_type_classifier import ImageTypeHead, active_head, image_features
from backend.app.services.ingest_state import ItemEvent
from backend.app.services.linked_files import sync_files
from backend.app.services.memory_budget import get_memory_budget
from backend.app.services.originals import OriginalUnavailable, linked_folder
from backend.app.services.validation import verify_media_mime

from .error_classifier import KIND_FILE, KIND_SYSTEM, classify_ingest_error
from .filename_grid import filename_grid_counts
from .image_hashes import perceptual_hash, pixel_hash
from .ingest_queue import (
    AUTO,
    BATTLEMAP,
    KIND_BYTES_LOST,
    KIND_SOURCE_CHANGED,
    KIND_SOURCE_UNAVAILABLE,
    REFUNDED_KINDS,
    SCENE,
    ClaimedItem,
    EarlyDuplicate,
    ItemFailure,
    RefreshUnchanged,
    SortedOut,
    effective_parsed,
    finish_committed,
    finish_refresh_gone,
    library_byte_duplicate,
    missing_roots,
    recompute_job_status,
    record_early_duplicates,
    record_failures,
    record_refresh_unchanged,
    record_sorted_out,
    remove_staged,
    staged_path,
    staging_dir_for,
    write_session,
)
from .linked_refresh import RefreshTarget, grid_snapshot, refresh_grid, refreshed_image
from .pipeline_config import PipelineConfig
from .stored_format import FORMAT_ORIGINAL
from .stored_format import convert as convert_stored_format
from .tasks import color_extraction, embedding_generation, grid_detection
from .tasks.image_processing import write_thumbnails

logger = logging.getLogger(__name__)

INCOMING_DIRNAME = ".incoming"
_BYTES_LOST_REASON = "The uploaded file is missing; upload it again"
_SOURCE_GONE_REASON = "The file was moved or deleted after it was chosen"
_LINKED_GONE_REASON = "The file was moved or deleted"
_SOURCE_CHANGED_REASON = "The file changed while it was read"
_MIME_MISMATCH_REASON = "File content doesn't match its type"


def incoming_dir(store_base: Path) -> Path:
    """Temp directory on the same volume as a store, so placement is an atomic rename."""
    return store_base / INCOMING_DIRNAME


def clear_incoming() -> None:
    """Delete leftover temp files (startup: anything here belongs to a dead batch)."""
    for store in (get_image_store(), get_thumbnail_store()):
        shutil.rmtree(incoming_dir(store.base_dir), ignore_errors=True)


# Prepare


@dataclass
class DecodedItem:
    """Prepare up to (not including) grid detection and storing the original: everything
    that doesn't depend on the image type. Auto items wait here for the image-type head."""

    item: ClaimedItem
    source: Path  # the bytes to finish from: the staged upload, or our own temp copy
    owned: bool  # ``source`` is this item's temp copy in the library's temp folder
    stem: str
    plan: DecodePlan
    temp_thumbnails: dict[str, Path]  # thumbnail_key → temp path
    thumbnail_key: str  # medium size: stored on the Image row, embedded, and the preview
    clip_source: Path
    width: int
    height: int
    file_size: int
    source_hash: str
    pixel_hash: str | None
    phash: int | None
    colors: list[dict]
    features: dict[str, float] | None = None  # image-type head inputs (Auto items)
    embedding: list[float] | None = None
    classification: dict | None = None  # Auto items: the image-type head's verdict

    def temp_paths(self) -> list[Path]:
        return [*self.temp_thumbnails.values(), *([self.source] if self.owned else [])]

    def discard(self) -> None:
        for path in self.temp_paths():
            path.unlink(missing_ok=True)


@dataclass
class PreparedItem:
    """A decoded item with its type-dependent steps done: ready to embed and commit."""

    decoded: DecodedItem
    storage_key: str | None  # None: a linked item, whose original stays where it is
    temp_original: Path | None  # the stored original, placed at commit
    stored_hash: str
    file_size: int  # of the stored file
    media_type: str
    grid: dict = field(default_factory=dict)

    @property
    def item(self) -> ClaimedItem:
        return self.decoded.item

    def temp_paths(self) -> list[Path]:
        originals = [self.temp_original] if self.temp_original is not None else []
        return [*originals, *self.decoded.temp_thumbnails.values()]

    def discard(self) -> None:
        for path in self.temp_paths():
            path.unlink(missing_ok=True)


type Prepared = PreparedItem | DecodedItem | ItemFailure | EarlyDuplicate | RefreshUnchanged


def _detect_grid(item: ClaimedItem, staged: Path, width: int, height: int, cfg) -> dict:
    """Filename-derived grid info, refined by image analysis when enabled (battlemaps only)."""
    parsed = item.parsed
    grid = {
        "gridded": parsed.get("gridded"),
        **filename_grid_counts(parsed, width, height),
        "grid_type": parsed.get("grid_type"),
        "grid_confidence": None,
        "grid_source": GRID_SOURCE_FILENAME
        if any(parsed.get(k) is not None for k in GRID_FIELDS)
        else None,
    }
    if not cfg.enable_image_grid_detection or item.image_type != "battlemap":
        return grid
    if grid["gridded"] is None:
        size_only = False
    elif grid["gridded"] is True and grid["grid_width"] is None:
        size_only = True
    else:
        return grid
    result = grid_detection.detect_grid_from_image(
        str(staged),
        width,
        height,
        size_only=size_only,
        pipeline_config=cfg,
        sibling_counts=item.sibling_grid_counts if size_only else (),
    )
    if result and result.get("confidence", 0) > 0:
        if grid["gridded"] is None:
            grid["gridded"] = result.get("gridded")
        if result.get("grid_width") is not None:
            grid["grid_width"] = result["grid_width"]
            grid["grid_height"] = result["grid_height"]
        grid["grid_type"] = result.get("grid_type")
        grid["grid_confidence"] = result.get("confidence")
        if not size_only:  # size-only: "gridded" still comes from the file name
            grid["grid_source"] = GRID_SOURCE_DETECTOR
    return grid


@dataclass(frozen=True)
class DecodePlan:
    """How an image will be decoded, and the memory to reserve for it."""

    width: int
    height: int
    full_decode: bool  # False: JPEG decoded at reduced scale, no pixel hash
    peak_bytes: int
    image_format: str | None = None
    progressive: bool = False


# Pillow holds RGB(A) at 4 bytes/px; the extra quarter covers thumbnails and strips.
_DECODE_BYTES_PER_PIXEL = 5
_VIDEO_PEAK_BYTES = 256 * 1024 * 1024
_MB = 1024 * 1024

# Grid detection v3 peak memory, measured per format on 2,400 real maps at full
# resolution: (fixed MB, MB per megapixel, safety factor covering the worst measured
# image). Formats Pillow decodes for us (TIFF, AVIF, ...) use the WebP row, the most
# conservative. See design/grid-detection-v3.md, round 5.
_GRID_MEMORY = {
    "JPEG": (42, 2.0, 1.8),
    "JPEG_PROGRESSIVE": (38, 5.9, 1.15),
    "PNG": (37, 1.8, 1.2),
    "WEBP": (24, 3.8, 1.5),
}


# A progressive JPEG's DCT coefficients are buffered for the whole image before
# any (even reduced-scale) output is produced: ~6 bytes/px whatever the scale.
_PROGRESSIVE_BYTES_PER_PIXEL = 6


def grid_detection_bytes(
    width: int, height: int, image_format: str | None, progressive: bool, cfg: PipelineConfig
) -> int:
    """Estimated peak memory of grid detection for one image.

    Only baseline JPEGs benefit from ``grid_analysis_max_dim`` (DCT-scaled decode);
    progressive JPEGs buffer every coefficient and other formats decode in full.
    """
    from backend.app.services.grid.analysis import reduction_factor

    if image_format == "JPEG":
        key = "JPEG_PROGRESSIVE" if progressive else "JPEG"
    else:
        key = image_format if image_format in _GRID_MEMORY else "WEBP"
    fixed_mb, per_mpx, safety = _GRID_MEMORY[key]
    pixels = width * height
    if key == "JPEG":
        factor = reduction_factor(max(width, height), cfg.grid_max_dim)
        pixels //= factor * factor
    return int((fixed_mb + per_mpx * pixels / 1e6) * safety * _MB)


def plan_decode(staged: Path, item: ClaimedItem, cfg: PipelineConfig) -> DecodePlan:
    """Read only the header and decide how to decode (design §5.3, Phase 0 follow-ups).

    JPEGs over ``settings.pixel_hash_max_pixels`` are decoded at reduced scale
    (libjpeg DCT scaling); every downstream stage except the pixel hash only needs
    an 800 px image. That caps baseline JPEGs at tens of megabytes. Progressive
    JPEGs still buffer their whole coefficient array, and PNG/WebP are always
    decoded in full, so their estimates reflect that (Phase 0 grid-cap study).
    """
    if item.kind == "video":
        return DecodePlan(0, 0, False, _VIDEO_PEAK_BYTES)
    with PILImage.open(staged) as header:
        width, height = header.size
        image_format = header.format
        progressive = bool(header.info.get("progressive") or header.info.get("progression"))
    pixels = width * height
    is_jpeg = image_format == "JPEG"
    full_decode = not (is_jpeg and pixels > settings.pixel_hash_max_pixels)
    decoded_pixels = pixels if full_decode else max(pixels // 64, 800 * 800)
    peak = decoded_pixels * _DECODE_BYTES_PER_PIXEL
    if is_jpeg and progressive:
        peak = max(peak, pixels * _PROGRESSIVE_BYTES_PER_PIXEL)
    if item.image_type == BATTLEMAP and cfg.enable_image_grid_detection:
        peak = max(peak, grid_detection_bytes(width, height, image_format, progressive, cfg))
    return DecodePlan(width, height, full_decode, peak, image_format, progressive)


def finish_peak_bytes(decoded: DecodedItem, cfg: PipelineConfig) -> int:
    """Memory to reserve when an Auto item is finished after sorting: grid detection
    (battlemaps) and stored-format conversion each decode the image again."""
    item, plan = decoded.item, decoded.plan
    if item.kind == "video":
        return 0
    peak = 0
    if cfg.stored_format.format != FORMAT_ORIGINAL:
        peak = plan.width * plan.height * _DECODE_BYTES_PER_PIXEL
    if item.image_type == BATTLEMAP and cfg.enable_image_grid_detection:
        grid = grid_detection_bytes(
            plan.width, plan.height, plan.image_format, plan.progressive, cfg
        )
        peak = max(peak, grid)
    return peak


def prepare_item(item: ClaimedItem, cfg: PipelineConfig) -> Prepared:
    """Everything except embedding and saving. Runs on the prepare pool.

    Reserves the image's estimated peak memory from the shared budget, then
    decodes once (in full, or at reduced scale for huge JPEGs) for the pixel hash
    and thumbnails. Colours and the perceptual hash come from the large
    thumbnail; only grid detection re-reads the file. Auto items stop after decoding
    (a ``DecodedItem``) and are finished by ``finish_item`` once sorted.
    """
    if item.source_file_id is not None:
        return _prepare_linked(item, cfg)
    if item.source_path:
        return _prepare_local(item, cfg)
    staged = staged_path(item.job_id, item.staging_key) if item.staging_key else None
    if staged is None or not staged.exists():
        return ItemFailure(
            item.id,
            KIND_BYTES_LOST,
            "copy",
            _BYTES_LOST_REASON,
        )

    progress = _Progress()
    try:
        plan = plan_decode(staged, item, cfg)
        with get_memory_budget().reserve(plan.peak_bytes):
            return _decode_and_finish(item, cfg, staged, plan, progress)
    except Exception as exc:
        return _prepare_failed(item, exc, progress, staged)


@dataclass
class _Progress:
    stage: str = "decode"
    created: list[Path] = field(default_factory=list)


def _prepare_failed(
    item: ClaimedItem, exc: Exception, progress: _Progress, staged: Path
) -> ItemFailure:
    """Delete what prepare created and say why it failed. A missing file is never the
    file's fault: an upload's staged bytes are asked for again, a local import's source
    is waited for (its folder is gone) or reported as moved."""
    for path in progress.created:
        path.unlink(missing_ok=True)
    stage = progress.stage
    if isinstance(exc, FileNotFoundError):
        if item.source_file_id is not None:
            return _linked_unreadable(item, str(exc))
        if item.source_path:
            if not Path(item.source_path).is_file():
                return _missing_source(item, str(exc))
        elif not staged.exists():
            return ItemFailure(item.id, KIND_BYTES_LOST, stage, _BYTES_LOST_REASON, str(exc))
    logger.warning("Prepare failed for %s at %s: %s", item.relative_path, stage, exc)
    return _classified_failure(item, exc, stage)


def _classified_failure(item: ClaimedItem, exc: Exception, stage: str) -> ItemFailure:
    """A failure classified from its exception, with the version of a linked file read."""
    info = classify_ingest_error(exc, stage=stage)
    return ItemFailure(
        item.id,
        info["kind"],
        stage,
        info["reason"],
        info["detail"],
        source_version=item.source_version,
    )


def _missing_source(item: ClaimedItem, detail: str = "") -> ItemFailure:
    """A local item's file isn't there: its folder is gone (wait), or just the file (fail)."""
    source = Path(item.source_path or "")
    gone = [root for root in missing_roots(item.source_roots) if source.is_relative_to(root)]
    if gone:
        return ItemFailure(
            item.id, KIND_SOURCE_UNAVAILABLE, "read", f"Waiting for {gone[0]}", detail
        )
    return ItemFailure(item.id, KIND_FILE, "read", _SOURCE_GONE_REASON, detail)


def _linked_unreadable(item: ClaimedItem, detail: str = "") -> ItemFailure:
    """A linked item's file can't be read: its folder is unavailable (wait: the job's
    root is the folder, so the job waits too), or the file is gone (fail)."""
    folder = linked_folder()
    if folder is None or not folder.available():
        name = folder.name if folder is not None else "the maps folder"
        reason = f"Waiting for {name}"
        return ItemFailure(item.id, KIND_SOURCE_UNAVAILABLE, "read", reason, detail)
    return ItemFailure(item.id, KIND_FILE, "read", _LINKED_GONE_REASON, detail)


def _linked_version(item: ClaimedItem) -> tuple[Path, tuple[int, int]] | ItemFailure:
    """The linked item's file, through the linked folder (with its containment check),
    and its (size, mtime) now."""
    folder = linked_folder()
    if folder is None:
        return _linked_unreadable(item)
    try:
        path = folder.local_path(item.source_key or "")
        info = path.stat()
    except (OriginalUnavailable, OSError) as exc:
        return _linked_unreadable(item, str(exc))
    return path, (info.st_size, info.st_mtime_ns)


def _prepare_linked(item: ClaimedItem, cfg: PipelineConfig) -> Prepared:
    """A linked item's file (design/library-setup.md §4.4): ``_prepare_local`` without the
    copy. The file is hashed, decoded and grid-detected where it is; stored format doesn't
    apply. Its (size, mtime) is noted now and checked again before commit.

    A refresh (§4.5) whose bytes are its image's has nothing to redo. Otherwise it isn't
    checked for duplicates: the edited file is its image's original whatever it holds."""
    progress = _Progress(stage="read")
    found = _linked_version(item)
    if isinstance(found, ItemFailure):
        return found
    source, version = found
    item = replace(item, source_version=version)
    try:
        if not verify_media_mime(source, source.suffix.lower()):
            return ItemFailure(
                item.id, KIND_FILE, "validate", _MIME_MISMATCH_REASON, source_version=version
            )
        source_hash = file_sha256(source)
        if item.refresh is not None:
            if source_hash == item.refresh.content_hash:
                return RefreshUnchanged(item.id, item.refresh.image_id, source_hash, version)
        else:
            duplicate_of = None if item.allow_duplicate else library_byte_duplicate(source_hash)
            if duplicate_of is not None:
                return EarlyDuplicate(item.id, duplicate_of, source_hash, version)

        progress.stage = "decode"
        plan = plan_decode(source, item, cfg)
        with get_memory_budget().reserve(plan.peak_bytes):
            linked = replace(item, source_hash=source_hash)
            return _decode_and_finish(linked, cfg, source, plan, progress)
    except Exception as exc:
        return _prepare_failed(item, exc, progress, source)


def _prepare_local(item: ClaimedItem, cfg: PipelineConfig) -> Prepared:
    """A local import's file (design/local-ingest.md §4.3): hash it where it is, skip it if
    the library has those bytes, else copy it into the library's temp folder once and
    process the copy. The source is read twice at most and never written."""
    source = Path(item.source_path or "")
    progress = _Progress(stage="read")
    try:
        if not source.is_file():
            return _missing_source(item)
        ext = source.suffix.lower()
        if not verify_media_mime(source, ext):
            return ItemFailure(item.id, KIND_FILE, "validate", _MIME_MISMATCH_REASON)
        source_hash = file_sha256(source)
        duplicate_of = None if item.allow_duplicate else library_byte_duplicate(source_hash)
        if duplicate_of is not None:
            return EarlyDuplicate(item.id, duplicate_of, source_hash)

        progress.stage = "copy"
        stem = uuid.uuid4().hex
        temp_dir = incoming_dir(get_image_store().base_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        copy = temp_dir / f"{stem}{ext}"
        progress.created.append(copy)
        shutil.copyfile(source, copy)

        progress.stage = "decode"
        plan = plan_decode(copy, item, cfg)
        with get_memory_budget().reserve(plan.peak_bytes):
            local = replace(item, source_hash=source_hash)
            return _decode_and_finish(local, cfg, copy, plan, progress, stem=stem, owned=True)
    except Exception as exc:
        return _prepare_failed(item, exc, progress, source)


def _decode_and_finish(
    item: ClaimedItem,
    cfg: PipelineConfig,
    staged: Path,
    plan: DecodePlan,
    progress: _Progress,
    *,
    stem: str | None = None,
    owned: bool = False,
) -> PreparedItem | DecodedItem:
    """Decode, then finish in the same memory reservation, unless the type isn't known yet."""
    decoded = _decode(item, cfg, staged, plan, progress, stem=stem, owned=owned)
    if item.image_type == AUTO:
        return decoded
    return _finish(decoded, cfg, progress)


def _decode(
    item: ClaimedItem,
    cfg: PipelineConfig,
    staged: Path,
    plan: DecodePlan,
    progress: _Progress,
    *,
    stem: str | None = None,
    owned: bool = False,
) -> DecodedItem:
    """Hashes, thumbnails, perceptual hash, colours and (Auto) the head's image features.

    ``owned``: ``staged`` is already this item's temp copy in the library's temp folder
    (named ``stem`` + extension), so it becomes the stored original without another copy.
    """
    thumbnail_store = get_thumbnail_store()
    stem = stem or uuid.uuid4().hex

    progress.stage = "hash"
    source_hash = item.source_hash or file_sha256(staged)
    file_size = staged.stat().st_size

    thumbs_dir = incoming_dir(thumbnail_store.base_dir)
    pictures = (
        _video_pictures(staged, stem, thumbs_dir, progress)
        if item.kind == "video"
        else _image_pictures(staged, stem, thumbs_dir, plan, progress)
    )
    thumbnails = pictures.thumbnails
    features = _head_features(thumbnails["large"][1], progress) if item.image_type == AUTO else None

    progress.stage = "colors"
    colors = color_extraction.extract_dominant_colors(
        str(thumbnails["large"][1]), pipeline_config=cfg
    )

    medium_key, medium_path = thumbnails["medium"]
    return DecodedItem(
        item=item,
        source=staged,
        owned=owned,
        stem=stem,
        plan=plan,
        temp_thumbnails=dict(thumbnails.values()),
        thumbnail_key=medium_key,
        clip_source=medium_path,
        width=pictures.width,
        height=pictures.height,
        file_size=file_size,
        source_hash=source_hash,
        pixel_hash=pictures.pixel_hash,
        phash=pictures.phash,
        colors=colors,
        features=features,
    )


def _head_features(large_thumbnail: Path, progress: _Progress) -> dict[str, float]:
    """The image-type head's image statistics, from the large thumbnail: the heads were
    trained on 800 px thumbnails."""
    progress.stage = "classify"
    with PILImage.open(large_thumbnail) as large:
        return image_features(large)


@dataclass(frozen=True)
class _Pictures:
    """What decoding gives: thumbnails ({size: (key, temp path)}), pixel size and hashes."""

    thumbnails: dict[str, tuple[str, Path]]
    width: int
    height: int
    pixel_hash: str | None
    phash: int | None


def _video_pictures(staged: Path, stem: str, thumbs_dir: Path, progress: _Progress) -> _Pictures:
    """Thumbnails from a video's first frame; videos get no pixel hash or pHash."""
    from backend.app.services.video_utils import extract_first_frame, get_video_dimensions

    progress.stage = "thumbnails"
    frame = extract_first_frame(staged)
    try:
        thumbnails = write_thumbnails(frame, stem, thumbs_dir)
    finally:
        frame.close()
    progress.created += [path for _, path in thumbnails.values()]
    width, height = get_video_dimensions(staged)
    return _Pictures(thumbnails, width, height, None, None)


def _image_pictures(
    staged: Path, stem: str, thumbs_dir: Path, plan: DecodePlan, progress: _Progress
) -> _Pictures:
    """Decode once (reduced scale for huge JPEGs) for the pixel hash and thumbnails; the
    perceptual hash reads the large thumbnail."""
    progress.stage = "decode"
    with PILImage.open(staged) as decoded:
        if not plan.full_decode:
            decoded.draft("RGB", (800, 800))
        decoded.load()
        progress.stage = "hash"
        image_pixel_hash = pixel_hash(decoded) if plan.full_decode else None
        progress.stage = "thumbnails"
        thumbnails = write_thumbnails(decoded, stem, thumbs_dir)
    progress.created += [path for _, path in thumbnails.values()]
    progress.stage = "hash"
    with PILImage.open(thumbnails["large"][1]) as large:
        image_phash = perceptual_hash(large)
    return _Pictures(thumbnails, plan.width, plan.height, image_pixel_hash, image_phash)


def _finish(decoded: DecodedItem, cfg: PipelineConfig, progress: _Progress) -> PreparedItem:
    """Grid detection (battlemaps) and the stored original: the steps that need the type."""
    item = decoded.item
    progress.stage = "grid_detection"
    if item.refresh is not None:  # only the columns re-detection may change
        grid = refresh_grid(item.refresh, decoded.source, decoded.width, decoded.height, cfg)
    elif item.kind != "video":
        grid = _detect_grid(item, decoded.source, decoded.width, decoded.height, cfg)
    else:
        grid = {
            "gridded": item.parsed.get("gridded"),
            **filename_grid_counts(item.parsed, decoded.width, decoded.height),
        }

    media_type = "video" if item.kind == "video" else "image"
    if item.source_file_id is not None:  # linked: the original stays where it is
        return PreparedItem(
            decoded=decoded,
            storage_key=None,
            temp_original=None,
            stored_hash=decoded.source_hash,
            file_size=decoded.file_size,
            media_type=media_type,
            grid=grid,
        )

    stored = _store_original(
        item,
        cfg,
        decoded.source,
        decoded.stem,
        decoded.source_hash,
        decoded.file_size,
        progress,
        owned=decoded.owned,
    )

    return PreparedItem(
        decoded=decoded,
        storage_key=stored.storage_key,
        temp_original=stored.path,
        stored_hash=stored.stored_hash,
        file_size=stored.size,
        media_type=media_type,
        grid=grid,
    )


def finish_item(decoded: DecodedItem, cfg: PipelineConfig) -> PreparedItem | ItemFailure:
    """Finish a sorted Auto item (runs on the prepare pool, in its own memory reservation)."""
    progress = _Progress(stage="grid_detection", created=decoded.temp_paths())
    try:
        with get_memory_budget().reserve(finish_peak_bytes(decoded, cfg)):
            return _finish(decoded, cfg, progress)
    except Exception as exc:
        return _prepare_failed(decoded.item, exc, progress, decoded.source)


@dataclass(frozen=True)
class _Stored:
    path: Path  # temp file in the library's temp folder, placed at commit
    storage_key: str
    stored_hash: str
    size: int


def _store_original(
    item: ClaimedItem,
    cfg: PipelineConfig,
    staged: Path,
    stem: str,
    source_hash: str,
    file_size: int,
    progress: _Progress,
    *,
    owned: bool,
) -> _Stored:
    """The stored original as a temp file next to the library: converted to the configured
    format, or the bytes as they are (``owned``: ``staged`` already is that copy)."""
    temp_dir = incoming_dir(get_image_store().base_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    progress.stage = "convert"
    converted = (
        convert_stored_format(staged, temp_dir, stem, cfg.stored_format)
        if item.kind != "video"
        else None
    )
    if converted is not None:
        progress.created.append(converted)
        if owned:
            staged.unlink(missing_ok=True)
        return _Stored(converted, converted.name, file_sha256(converted), converted.stat().st_size)
    key = f"{stem}{staged.suffix.lower()}"
    if owned:
        return _Stored(staged, key, source_hash, file_size)
    progress.stage = "copy"
    temp = temp_dir / key
    progress.created.append(temp)
    shutil.copyfile(staged, temp)
    return _Stored(temp, key, source_hash, file_size)


# Embed


def embed(decoded: list[DecodedItem]) -> list[ItemFailure]:
    """Generate embeddings for the batch in one call. On error every item fails together."""
    try:
        embeddings = embedding_generation.batch_generate_clip_embeddings(
            [str(d.clip_source) for d in decoded]
        )
    except Exception as exc:
        logger.exception("Batch embedding failed for %d item(s)", len(decoded))
        return [_classified_failure(d.item, exc, "embedding") for d in decoded]
    for d, embedding in zip(decoded, embeddings, strict=True):
        d.embedding = embedding
    return []


# Sort (Auto items, design §5.6)

_TYPE_FOR_GROUP = {"map": BATTLEMAP, "illustration": SCENE}
# Shown in the import report and the group editor, grouped by reason
SORTED_OUT_REASONS = {
    "token": "Looks like a token",
    "asset": "Looks like a map asset (a prop, overlay or tile)",
    "other": "Doesn't look like a map or a scene",
    "unsure": "Couldn't tell whether this is a map or a scene",
}

_mismatch_logged: set[str] = set()


def _usable_head(decoded: list[DecodedItem]) -> ImageTypeHead | None:
    """The active model's head, if it fits these embeddings."""
    head = active_head()
    if head is None:
        return None
    dims = {len(d.embedding or ()) for d in decoded}
    if dims != {head.embedding_dim}:
        if head.encoder_sha256 not in _mismatch_logged:
            _mismatch_logged.add(head.encoder_sha256)
            logger.warning(
                "Image-type head expects %d dims, embeddings have %s; Auto imports as battlemaps",
                head.embedding_dim,
                sorted(dims),
            )
        return None
    return head


def _preview_key(decoded: DecodedItem) -> str:
    """The item's preview in the job's staging folder: its medium thumbnail, renamed."""
    return f"preview-{decoded.stem}{decoded.temp_thumbnails[decoded.thumbnail_key].suffix}"


def _keep_preview(decoded: DecodedItem) -> str | None:
    """Move the medium thumbnail into the job's staging folder as the item's preview."""
    key = _preview_key(decoded)
    try:
        target = staging_dir_for(decoded.item.job_id)
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(decoded.temp_thumbnails[decoded.thumbnail_key], target / key)
    except OSError as exc:
        logger.warning("Couldn't keep a preview for %s: %s", decoded.item.relative_path, exc)
        return None
    return key


def sort_auto_items(decoded: list[DecodedItem]) -> tuple[list[DecodedItem], list[SortedOut]]:
    """Give each embedded Auto item its type from the image-type head. Maps and scenes are
    returned to be finished; tokens, map assets, other images and anything the head is unsure about
    (it falls back to "other") are sorted out, keeping a preview. Without a head for the
    active model, Auto items are imported as battlemaps."""
    head = _usable_head(decoded)
    kept: list[DecodedItem] = []
    sorted_out: list[SortedOut] = []
    for d in decoded:
        if head is None:
            d.item = replace(d.item, image_type=BATTLEMAP)
            kept.append(d)
            continue
        result = head.classify(d.embedding, features=d.features)
        classification = {
            "group": result.group,
            "probabilities": {g: round(p, 4) for g, p in result.probabilities.items()},
            "fell_back": result.fell_back,
            "head": head.encoder_version,
        }
        image_type = _TYPE_FOR_GROUP.get(result.group)
        if image_type is not None:
            d.item = replace(
                d.item, image_type=image_type, parsed=effective_parsed(image_type, d.item.parsed)
            )
            d.classification = classification
            kept.append(d)
            continue
        key = "unsure" if result.fell_back else result.group
        reason = SORTED_OUT_REASONS.get(key, SORTED_OUT_REASONS["other"])
        preview_key = _keep_preview(d)
        d.discard()
        sorted_out.append(SortedOut(d.item.id, reason, classification, preview_key))
    return kept, sorted_out


def _sort(decoded: list[DecodedItem]) -> tuple[list[DecodedItem], int, list[ItemFailure]]:
    """Sort the batch's Auto items and record the ones sorted out. Returns (items to
    finish, how many were sorted out, failures). If sorting fails, every Auto item in the
    batch fails (stage ``classify``) and nothing it made is left behind."""
    try:
        kept, sorted_out = sort_auto_items(decoded)
        record_sorted_out(sorted_out)
    except Exception as exc:
        logger.exception("Sorting failed for %d Auto item(s)", len(decoded))
        for d in decoded:
            d.discard()
            # A preview may already have been moved for it (the key is deterministic)
            remove_staged(d.item.job_id, _preview_key(d))
        return [], 0, [_classified_failure(d.item, exc, "classify") for d in decoded]
    return kept, len(sorted_out), []


# Commit


@dataclass(frozen=True)
class CommittedImage:
    prepared: PreparedItem
    image_id: int
    group_name: str | None
    author: str | None


@dataclass
class CommitResult:
    done: list[CommittedImage] = field(default_factory=list)
    duplicates: list[PreparedItem] = field(default_factory=list)
    # Refreshes (design/library-setup.md §4.5): the images updated in place, and the
    # thumbnails they replaced, deleted once the commit is durable
    refreshed: list[int] = field(default_factory=list)
    stale_thumbnails: list[str] = field(default_factory=list)


def _existing_hash_matches(db, prepared: list[PreparedItem]) -> tuple[dict, dict]:
    """Existing images matching the batch's byte or pixel hashes."""
    byte_hashes = {p.decoded.source_hash for p in prepared} | {p.stored_hash for p in prepared}
    pixel_hashes = {p.decoded.pixel_hash for p in prepared if p.decoded.pixel_hash}
    by_bytes: dict[str, int] = {}
    by_pixels: dict[str, int] = {}
    rows = (
        db.query(Image.id, Image.content_hash, Image.stored_hash, Image.pixel_hash)
        .filter(
            Image.content_hash.in_(byte_hashes)
            | Image.stored_hash.in_(byte_hashes)
            | Image.pixel_hash.in_(pixel_hashes)
        )
        .order_by(Image.id)
        .all()
    )
    for image_id, content_hash, stored_hash, image_pixel_hash in rows:
        for h in (content_hash, stored_hash):
            if h:
                by_bytes.setdefault(h, image_id)
        if image_pixel_hash:
            by_pixels.setdefault(image_pixel_hash, image_id)
    return by_bytes, by_pixels


def _resolve_group(db, import_group_id: int | None, cache: dict) -> tuple[ImageGroup | None, str]:
    """The gallery group for an import group, created on first use. Returns (group, name)."""
    if import_group_id is None:
        return None, ""
    if import_group_id in cache:
        return cache[import_group_id]
    import_group = db.get(ImportGroup, import_group_id)
    group = db.get(ImageGroup, import_group.image_group_id) if import_group.image_group_id else None
    if group is None:
        group = ImageGroup(base_name=import_group.group_name, author=import_group.author)
        db.add(group)
        db.flush()
        import_group.image_group_id = group.id
    cache[import_group_id] = (group, import_group.group_name)
    return cache[import_group_id]


def _place(temp: Path, final: Path, placed: list[Path]) -> None:
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp, final)
    placed.append(final)


def commit_batch(prepared: list[PreparedItem]) -> CommitResult:
    """Dedup, place files and write rows for the batch in one write transaction.

    Duplicate checks run inside the transaction, against the library and against
    earlier items in the same batch, so concurrent or in-batch duplicates can't
    both get in. Items with ``allow_duplicate`` ("Import as new copy") skip the
    check and become fully independent images.
    """
    image_store = get_image_store()
    thumbnail_store = get_thumbnail_store()
    result = CommitResult()
    placed: list[Path] = []
    try:
        with write_session() as db:
            by_bytes, by_pixels = _existing_hash_matches(db, prepared)
            group_cache: dict = {}
            item_rows = {
                row.id: row
                for row in db.query(ImportItem).filter(
                    ImportItem.id.in_([p.item.id for p in prepared])
                )
            }
            # Linked files that already are an image's (one image per file)
            taken = _linked_images(db, [p.item.source_file_id for p in prepared])
            for p in prepared:
                d = p.decoded
                row = item_rows.get(p.item.id)
                if row is None or row.state != st.PROCESSING:
                    logger.warning("Item %s no longer processing; discarding", p.item.id)
                    continue

                if p.item.refresh is not None:
                    _commit_refresh(
                        db, p, p.item.refresh, row, result, placed, (by_bytes, by_pixels)
                    )
                    continue

                tier, duplicate_of = None, None
                if p.item.source_file_id in taken:
                    tier, duplicate_of = "bytes", taken[p.item.source_file_id]
                elif not p.item.allow_duplicate:
                    if d.source_hash in by_bytes or p.stored_hash in by_bytes:
                        tier = "bytes"
                        duplicate_of = by_bytes.get(d.source_hash) or by_bytes[p.stored_hash]
                    elif d.pixel_hash and d.pixel_hash in by_pixels:
                        tier, duplicate_of = "pixels", by_pixels[d.pixel_hash]
                if tier:
                    row.state = st.next_item_state(row.state, ItemEvent.DUPLICATE_AT_COMMIT)
                    row.duplicate_of_image_id = duplicate_of
                    row.duplicate_tier = tier
                    row.source_hash = d.source_hash
                    result.duplicates.append(p)
                    continue

                if p.temp_original is not None and p.storage_key is not None:
                    _place(p.temp_original, image_store.get_path(p.storage_key), placed)
                for key, temp in d.temp_thumbnails.items():
                    _place(temp, thumbnail_store.get_path(key), placed)

                group, group_name = _resolve_group(db, p.item.import_group_id, group_cache)
                parsed = p.item.parsed
                author = group.author if group is not None else None
                name = parsed.get("name") or group_name or Path(p.item.filename).stem
                tags = parsed.get("tags") or []
                image = Image(
                    filename=p.item.filename,
                    storage_key=p.storage_key,
                    source_file_id=p.item.source_file_id,
                    name=name,
                    author=author,
                    group_id=group.id if group is not None else None,
                    width=d.width,
                    height=d.height,
                    file_size=p.file_size,
                    thumbnail_key=d.thumbnail_key,
                    gridded=p.grid.get("gridded"),
                    grid_width=p.grid.get("grid_width"),
                    grid_height=p.grid.get("grid_height"),
                    grid_type=p.grid.get("grid_type"),
                    grid_confidence=p.grid.get("grid_confidence"),
                    grid_source=p.grid.get("grid_source"),
                    subgroup=parsed.get("subgroup"),
                    image_type=p.item.image_type,
                    media_type=p.media_type,
                    content_hash=d.source_hash,
                    stored_hash=p.stored_hash,
                    pixel_hash=d.pixel_hash,
                    phash=d.phash,
                    import_job_id=p.item.job_id,
                    search_text=build_search_text(
                        name=name,
                        filename=p.item.filename,
                        author=author,
                        tags=tags,
                        subgroup=parsed.get("subgroup"),
                    ),
                )
                db.add(image)
                db.flush()
                for tag in tags:
                    db.add(
                        Tag(
                            image_id=image.id,
                            category=tag["category"],
                            value=tag["value"],
                            confidence=tag.get("confidence", 1.0),
                            source=tag.get("source", "auto"),
                        )
                    )
                _add_colors(db, image.id, d.colors)

                finish_committed(row, image.id, d.source_hash)
                if d.classification is not None:
                    row.classification = json.dumps(d.classification)
                # The staged file is deleted right after commit; a crash in between
                # leaves an unreferenced file for the stray-staging sweep.
                row.staging_key = None

                _index(p, image.id, (by_bytes, by_pixels))
                result.done.append(CommittedImage(p, image.id, group_name or None, author))

            db.flush()
            versions = {p.item.id: p.item.source_version for p in prepared if p.item.source_version}
            sync_files(db, item_rows.values(), versions)
            for job_id in {p.item.job_id for p in prepared}:
                recompute_job_status(db, job_id)
    except Exception:
        for path in placed:
            path.unlink(missing_ok=True)
        raise
    return result


def _add_colors(db, image_id: int, colors: list[dict]) -> None:
    for color in colors:
        db.add(
            Color(
                image_id=image_id,
                color_hex=color["color_hex"],
                percentage=color["percentage"],
                color_order=color["color_order"],
            )
        )


def _index(p: PreparedItem, image_id: int, matches: tuple[dict, dict]) -> None:
    """Later items in the batch dedup against this image too."""
    by_bytes, by_pixels = matches
    by_bytes.setdefault(p.decoded.source_hash, image_id)
    by_bytes.setdefault(p.stored_hash, image_id)
    if p.decoded.pixel_hash:
        by_pixels.setdefault(p.decoded.pixel_hash, image_id)


def _commit_refresh(
    db,
    p: PreparedItem,
    target: RefreshTarget,
    row: ImportItem,
    result: CommitResult,
    placed: list[Path],
    matches: tuple[dict, dict],
) -> None:
    """Update a refreshed linked image in place (design/library-setup.md §4.5), in the
    batch's transaction. Only columns that come from the file are written: name, author,
    tags, group and type stay the user's, and the grid only changes if nobody changed it
    since the item was claimed. An image removed meanwhile skips the item."""
    image = refreshed_image(db, target.image_id, p.item.source_file_id)
    if image is None:
        logger.info("Refresh of %s skipped: its image was removed", p.item.relative_path)
        finish_refresh_gone(row)
        return
    d = p.decoded
    thumbnail_store = get_thumbnail_store()
    for key, temp in d.temp_thumbnails.items():
        _place(temp, thumbnail_store.get_path(key), placed)

    by_bytes, by_pixels = matches
    for value, index in (
        (image.content_hash, by_bytes),
        (image.stored_hash, by_bytes),
        (image.pixel_hash, by_pixels),
    ):
        if value and index.get(value) == image.id:  # these bytes aren't the image's now
            del index[value]
    if image.thumbnail_key and image.thumbnail_key != d.thumbnail_key:
        result.stale_thumbnails.append(image.thumbnail_key)

    image.width, image.height = d.width, d.height
    image.file_size = p.file_size
    image.thumbnail_key = d.thumbnail_key
    image.content_hash = d.source_hash
    image.stored_hash = p.stored_hash
    image.pixel_hash = d.pixel_hash
    image.phash = d.phash
    if p.grid and grid_snapshot(image) == grid_snapshot(target):
        for column, value in p.grid.items():
            setattr(image, column, value)
    db.execute(delete(Color).where(Color.image_id == image.id))
    _add_colors(db, image.id, d.colors)

    finish_committed(row, image.id, d.source_hash)
    _index(p, image.id, matches)
    group = db.get(ImageGroup, image.group_id) if image.group_id is not None else None
    result.done.append(
        CommittedImage(p, image.id, group.base_name if group else None, image.author)
    )
    result.refreshed.append(image.id)


def _linked_images(db, file_ids: list[int | None]) -> dict[int, int]:
    """file id → image id, for linked files that already have an image."""
    ids = [i for i in file_ids if i is not None]
    if not ids:
        return {}
    rows = db.query(Image.source_file_id, Image.id).filter(Image.source_file_id.in_(ids))
    return dict(cast(Iterable[tuple[int, int]], rows))


def changed_since_read(prepared: list[PreparedItem]) -> list[ItemFailure]:
    """Linked items whose file changed (or went) since prepare read it: they go back to
    the queue rather than commit what was read from a file being written (§4.4)."""
    changed: list[ItemFailure] = []
    for p in prepared:
        if p.item.source_file_id is None:
            continue
        found = _linked_version(p.item)
        if isinstance(found, ItemFailure):
            changed.append(found)
        elif found[1] != p.item.source_version:
            changed.append(
                ItemFailure(p.item.id, KIND_SOURCE_CHANGED, "commit", _SOURCE_CHANGED_REASON)
            )
    return changed


# Vectors


def write_vectors(done: list[CommittedImage], refreshed: Iterable[int] = ()) -> bool:
    """Write embeddings for committed images. Failures are repaired by reconciliation,
    which embeds images without a vector: a refreshed image's old vector is deleted if
    the new one couldn't be written, so it is embedded again rather than kept stale."""
    items = [
        {
            "image_id": c.image_id,
            "embedding": c.prepared.decoded.embedding,
            "metadata": {
                "filename": c.prepared.item.filename,
                "author": c.author or "",
                "base_name": c.group_name or "",
            },
        }
        for c in done
        if c.prepared.decoded.embedding is not None
    ]
    if not items:
        return True
    try:
        ok = get_lancedb_service().batch_add_embeddings(items)
    except Exception:
        ok = False
    if not ok:
        logger.warning(
            "Vector write failed for %d image(s); reconciliation will repair", len(items)
        )
        _drop_stale_vectors(list(refreshed))
    return bool(ok)


def _drop_stale_vectors(image_ids: list[int]) -> None:
    if not image_ids:
        return
    try:
        get_lancedb_service().delete_embeddings(image_ids)
    except Exception:
        logger.warning("Couldn't drop the old vectors of %d refreshed image(s)", len(image_ids))


# Orchestration


@dataclass
class BatchOutcome:
    done: int = 0
    duplicates: int = 0
    sorted_out: int = 0
    failures: list[ItemFailure] = field(default_factory=list)
    system_reason: str | None = None


def settled_count(items: list[ClaimedItem], outcome: BatchOutcome) -> int:
    """Files the batch finished with (imported, duplicate or failed). Refunded ones (a
    system pause, a missing folder) go back to the queue and weren't processed."""
    return len(items) - sum(1 for f in outcome.failures if f.kind in REFUNDED_KINDS)


@dataclass
class _Split:
    prepared: list[PreparedItem]
    decoded: list[DecodedItem]  # Auto items waiting to be sorted
    failures: list[ItemFailure]
    early: list[EarlyDuplicate]
    unchanged: list[RefreshUnchanged]  # refreshes of files only touched


def _split(results: list[Prepared]) -> _Split:
    return _Split(
        prepared=[r for r in results if isinstance(r, PreparedItem)],
        decoded=[r for r in results if isinstance(r, DecodedItem)],
        failures=[r for r in results if isinstance(r, ItemFailure)],
        early=[r for r in results if isinstance(r, EarlyDuplicate)],
        unchanged=[r for r in results if isinstance(r, RefreshUnchanged)],
    )


def process_batch(items: list[ClaimedItem], cfg: PipelineConfig, pool) -> BatchOutcome:
    """Prepare, embed, sort (Auto), commit and index one claimed batch. Never raises for
    item errors."""
    outcome = BatchOutcome()
    split = _split([f.result() for f in [pool.submit(prepare_item, item, cfg) for item in items]])
    prepared, decoded, outcome.failures = split.prepared, split.decoded, split.failures
    record_early_duplicates(split.early)
    record_refresh_unchanged(split.unchanged)

    if prepared or decoded:
        embed_failures = embed([*(p.decoded for p in prepared), *decoded])
        if embed_failures:
            for p in [*prepared, *decoded]:
                p.discard()
            outcome.failures += embed_failures
            prepared, decoded = [], []

    if decoded:
        kept, outcome.sorted_out, sort_failures = _sort(decoded)
        outcome.failures += sort_failures
        finished = _split([f.result() for f in [pool.submit(finish_item, d, cfg) for d in kept]])
        prepared += finished.prepared
        outcome.failures += finished.failures

    if prepared:
        changed = changed_since_read(prepared)
        if changed:
            failed = {f.item_id for f in changed}
            for p in prepared:
                if p.item.id in failed:
                    p.discard()
            prepared = [p for p in prepared if p.item.id not in failed]
            outcome.failures += changed

    commit: CommitResult | None = None
    if prepared:
        try:
            commit = commit_batch(prepared)
        except Exception as exc:
            logger.exception("Commit failed for %d item(s)", len(prepared))
            outcome.failures += [_classified_failure(p.item, exc, "db_save") for p in prepared]
        finally:
            for p in prepared:
                p.discard()  # no-op for files already placed

    record_failures(outcome.failures)
    system = [f for f in outcome.failures if f.kind == KIND_SYSTEM]
    outcome.system_reason = system[0].reason if system else None

    if commit is not None:
        write_vectors(commit.done, commit.refreshed)
        for c in commit.done:
            remove_staged(c.prepared.item.job_id, c.prepared.item.staging_key)
        # Replaced by a refresh; any left behind are unreferenced, for the orphan sweep
        PendingFileDeletes(thumbnail_keys=commit.stale_thumbnails).apply()
        outcome.done = len(commit.done)
        outcome.duplicates = len(commit.duplicates)
    outcome.done += len(split.unchanged)
    outcome.duplicates += len(split.early)

    logger.info(
        "Ingest batch: %d done, %d duplicate, %d sorted out, %d failed",
        outcome.done,
        outcome.duplicates,
        outcome.sorted_out,
        len(outcome.failures),
    )
    return outcome

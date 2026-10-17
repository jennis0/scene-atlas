"""Process one claimed batch of import items (ADR-018, design/ingestion.md §5.3).

    prepare (prepare pool) → embed (one batch) → commit (one BEGIN IMMEDIATE
    transaction) → vectors (LanceDB, after commit) → staging cleanup

A file is either fully in the library (row, stored file, thumbnails) or not at
all. Prepare writes the stored original and thumbnails as temp files next to
their destinations (``<store>/.incoming/``); the commit renames them into place
inside the transaction and deletes them again if the transaction fails. Vectors
are written after the commit; a failure there is repaired by
``vector_reconcile``.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image as PILImage

from backend.app.config import settings
from backend.app.models import Color, Image, ImageGroup, ImportGroup, ImportItem, Tag
from backend.app.models.database import GRID_FIELDS, GRID_SOURCE_DETECTOR, GRID_SOURCE_FILENAME
from backend.app.services import (
    get_image_store,
    get_lancedb_service,
    get_thumbnail_store,
)
from backend.app.services import ingest_state as st
from backend.app.services.image_parser import build_search_text
from backend.app.services.ingest_state import ItemEvent
from backend.app.services.memory_budget import get_memory_budget

from .error_classifier import KIND_SYSTEM, classify_ingest_error
from .image_hashes import file_sha256, perceptual_hash, pixel_hash
from .ingest_queue import (
    KIND_BYTES_LOST,
    ClaimedItem,
    ItemFailure,
    recompute_job_status,
    record_failures,
    remove_staged,
    staged_path,
    write_session,
)
from .pipeline_config import PipelineConfig
from .stored_format import convert as convert_stored_format
from .tasks import color_extraction, embedding_generation, grid_detection
from .tasks.image_processing import write_thumbnails

logger = logging.getLogger(__name__)

INCOMING_DIRNAME = ".incoming"
_BYTES_LOST_REASON = "The uploaded file is missing; upload it again"


def incoming_dir(store_base: Path) -> Path:
    """Temp directory on the same volume as a store, so placement is an atomic rename."""
    return store_base / INCOMING_DIRNAME


def clear_incoming() -> None:
    """Delete leftover temp files (startup: anything here belongs to a dead batch)."""
    for store in (get_image_store(), get_thumbnail_store()):
        shutil.rmtree(incoming_dir(store.base_dir), ignore_errors=True)


# Prepare


@dataclass
class PreparedItem:
    item: ClaimedItem
    storage_key: str
    temp_original: Path
    temp_thumbnails: dict[str, Path]  # thumbnail_key → temp path
    thumbnail_key: str  # medium size, stored on the Image row
    clip_source: Path
    width: int
    height: int
    file_size: int
    media_type: str
    source_hash: str
    stored_hash: str
    pixel_hash: str | None
    phash: int | None
    colors: list[dict]
    grid: dict = field(default_factory=dict)
    embedding: list[float] | None = None

    def temp_paths(self) -> list[Path]:
        return [self.temp_original, *self.temp_thumbnails.values()]

    def discard(self) -> None:
        for path in self.temp_paths():
            path.unlink(missing_ok=True)


def _detect_grid(item: ClaimedItem, staged: Path, width: int, height: int, cfg) -> dict:
    """Filename-derived grid info, refined by image analysis when enabled (battlemaps only)."""
    parsed = item.parsed
    grid = {
        "gridded": parsed.get("gridded"),
        "grid_width": parsed.get("grid_width"),
        "grid_height": parsed.get("grid_height"),
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
    if item.image_type == "battlemap" and cfg.enable_image_grid_detection:
        peak = max(peak, grid_detection_bytes(width, height, image_format, progressive, cfg))
    return DecodePlan(width, height, full_decode, peak)


def prepare_item(item: ClaimedItem, cfg: PipelineConfig) -> PreparedItem | ItemFailure:
    """Everything except embedding and saving. Runs on the prepare pool.

    Reserves the image's estimated peak memory from the shared budget, then
    decodes once (in full, or at reduced scale for huge JPEGs) for the pixel hash
    and thumbnails. Colours and the perceptual hash come from the large
    thumbnail; only grid detection re-reads the file.
    """
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
            return _prepare(item, cfg, staged, plan, progress)
    except Exception as exc:
        for path in progress.created:
            path.unlink(missing_ok=True)
        stage = progress.stage
        if isinstance(exc, FileNotFoundError) and not staged.exists():
            return ItemFailure(item.id, KIND_BYTES_LOST, stage, _BYTES_LOST_REASON, str(exc))
        logger.warning("Prepare failed for %s at %s: %s", item.relative_path, stage, exc)
        info = classify_ingest_error(exc, stage=stage)
        return ItemFailure(item.id, info["kind"], stage, info["reason"], info["detail"])


@dataclass
class _Progress:
    stage: str = "decode"
    created: list[Path] = field(default_factory=list)


def _prepare(
    item: ClaimedItem, cfg: PipelineConfig, staged: Path, plan: DecodePlan, progress: _Progress
) -> PreparedItem:
    image_store = get_image_store()
    thumbnail_store = get_thumbnail_store()
    stem = uuid.uuid4().hex
    storage_key = f"{stem}{staged.suffix.lower()}"

    progress.stage = "hash"
    source_hash = item.source_hash or file_sha256(staged)
    file_size = staged.stat().st_size

    thumbs_dir = incoming_dir(thumbnail_store.base_dir)
    if item.kind == "video":
        from backend.app.services.video_utils import extract_first_frame, get_video_dimensions

        progress.stage = "thumbnails"
        frame = extract_first_frame(staged)
        try:
            thumbnails = write_thumbnails(frame, stem, thumbs_dir)
        finally:
            frame.close()
        progress.created += [path for _, path in thumbnails.values()]
        width, height = get_video_dimensions(staged)
        image_pixel_hash = None
        image_phash = None
    else:
        width, height = plan.width, plan.height
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

    progress.stage = "colors"
    colors = color_extraction.extract_dominant_colors(
        str(thumbnails["large"][1]), pipeline_config=cfg
    )

    progress.stage = "grid_detection"
    grid = (
        _detect_grid(item, staged, width, height, cfg)
        if item.kind != "video"
        else {k: item.parsed.get(k) for k in ("gridded", "grid_width", "grid_height")}
    )

    library_temp_dir = incoming_dir(image_store.base_dir)
    library_temp_dir.mkdir(parents=True, exist_ok=True)
    progress.stage = "convert"
    converted = (
        convert_stored_format(staged, library_temp_dir, stem, cfg.stored_format)
        if item.kind != "video"
        else None
    )
    if converted is not None:
        progress.created.append(converted)
        temp_original = converted
        storage_key = converted.name
        stored_hash = file_sha256(converted)
        file_size = converted.stat().st_size
    else:
        progress.stage = "copy"
        temp_original = library_temp_dir / storage_key
        progress.created.append(temp_original)
        shutil.copyfile(staged, temp_original)
        stored_hash = source_hash

    medium_key, medium_path = thumbnails["medium"]
    return PreparedItem(
        item=item,
        storage_key=storage_key,
        temp_original=temp_original,
        temp_thumbnails=dict(thumbnails.values()),
        thumbnail_key=medium_key,
        clip_source=medium_path,
        width=width,
        height=height,
        file_size=file_size,
        media_type="video" if item.kind == "video" else "image",
        source_hash=source_hash,
        stored_hash=stored_hash,
        pixel_hash=image_pixel_hash,
        phash=image_phash,
        colors=colors,
        grid=grid,
    )


# Embed


def embed(prepared: list[PreparedItem]) -> list[ItemFailure]:
    """Generate embeddings for the batch in one call. On error every item fails together."""
    try:
        embeddings = embedding_generation.batch_generate_clip_embeddings(
            [str(p.clip_source) for p in prepared]
        )
    except Exception as exc:
        logger.exception("Batch embedding failed for %d item(s)", len(prepared))
        info = classify_ingest_error(exc, stage="embedding")
        return [
            ItemFailure(p.item.id, info["kind"], "embedding", info["reason"], info["detail"])
            for p in prepared
        ]
    for p, embedding in zip(prepared, embeddings, strict=True):
        p.embedding = embedding
    return []


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


def _existing_hash_matches(db, prepared: list[PreparedItem]) -> tuple[dict, dict]:
    """Existing images matching the batch's byte or pixel hashes."""
    byte_hashes = {p.source_hash for p in prepared} | {p.stored_hash for p in prepared}
    pixel_hashes = {p.pixel_hash for p in prepared if p.pixel_hash}
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
            for p in prepared:
                row = item_rows.get(p.item.id)
                if row is None or row.state != st.PROCESSING:
                    logger.warning("Item %s no longer processing; discarding", p.item.id)
                    continue

                if not p.item.allow_duplicate:
                    tier, duplicate_of = None, None
                    if p.source_hash in by_bytes or p.stored_hash in by_bytes:
                        tier = "bytes"
                        duplicate_of = by_bytes.get(p.source_hash) or by_bytes[p.stored_hash]
                    elif p.pixel_hash and p.pixel_hash in by_pixels:
                        tier, duplicate_of = "pixels", by_pixels[p.pixel_hash]
                    if tier:
                        row.state = st.next_item_state(row.state, ItemEvent.DUPLICATE_AT_COMMIT)
                        row.duplicate_of_image_id = duplicate_of
                        row.duplicate_tier = tier
                        row.source_hash = p.source_hash
                        result.duplicates.append(p)
                        continue

                _place(p.temp_original, image_store.get_path(p.storage_key), placed)
                for key, temp in p.temp_thumbnails.items():
                    _place(temp, thumbnail_store.get_path(key), placed)

                group, group_name = _resolve_group(db, p.item.import_group_id, group_cache)
                parsed = p.item.parsed
                author = group.author if group is not None else None
                name = parsed.get("name") or group_name or Path(p.item.filename).stem
                tags = parsed.get("tags") or []
                image = Image(
                    filename=p.item.filename,
                    storage_key=p.storage_key,
                    name=name,
                    author=author,
                    group_id=group.id if group is not None else None,
                    width=p.width,
                    height=p.height,
                    file_size=p.file_size,
                    thumbnail_key=p.thumbnail_key,
                    gridded=p.grid.get("gridded"),
                    grid_width=p.grid.get("grid_width"),
                    grid_height=p.grid.get("grid_height"),
                    grid_type=p.grid.get("grid_type"),
                    grid_confidence=p.grid.get("grid_confidence"),
                    grid_source=p.grid.get("grid_source"),
                    subgroup=parsed.get("subgroup"),
                    image_type=p.item.image_type,
                    media_type=p.media_type,
                    content_hash=p.source_hash,
                    stored_hash=p.stored_hash,
                    pixel_hash=p.pixel_hash,
                    phash=p.phash,
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
                for color in p.colors:
                    db.add(
                        Color(
                            image_id=image.id,
                            color_hex=color["color_hex"],
                            percentage=color["percentage"],
                            color_order=color["color_order"],
                        )
                    )

                row.state = st.next_item_state(row.state, ItemEvent.COMMITTED)
                row.image_id = image.id
                row.source_hash = p.source_hash
                row.error_kind = row.error_stage = row.error_reason = row.error_detail = None
                # The staged file is deleted right after commit; a crash in between
                # leaves an unreferenced file for the stray-staging sweep.
                row.staging_key = None

                # Later items in this batch dedup against this one too.
                by_bytes.setdefault(p.source_hash, image.id)
                by_bytes.setdefault(p.stored_hash, image.id)
                if p.pixel_hash:
                    by_pixels.setdefault(p.pixel_hash, image.id)
                result.done.append(CommittedImage(p, image.id, group_name or None, author))

            for job_id in {p.item.job_id for p in prepared}:
                recompute_job_status(db, job_id)
    except Exception:
        for path in placed:
            path.unlink(missing_ok=True)
        raise
    return result


# Vectors


def write_vectors(done: list[CommittedImage]) -> bool:
    """Write embeddings for committed images. Failures are repaired by reconciliation."""
    items = [
        {
            "image_id": c.image_id,
            "embedding": c.prepared.embedding,
            "metadata": {
                "filename": c.prepared.item.filename,
                "author": c.author or "",
                "base_name": c.group_name or "",
            },
        }
        for c in done
        if c.prepared.embedding is not None
    ]
    if not items:
        return True
    try:
        ok = get_lancedb_service().batch_add_embeddings(items)
    except Exception:
        logger.warning(
            "Vector write failed for %d image(s); reconciliation will repair", len(items)
        )
        return False
    if not ok:
        logger.warning(
            "Vector write failed for %d image(s); reconciliation will repair", len(items)
        )
    return bool(ok)


# Orchestration


@dataclass
class BatchOutcome:
    done: int = 0
    duplicates: int = 0
    failures: list[ItemFailure] = field(default_factory=list)
    system_reason: str | None = None


def process_batch(items: list[ClaimedItem], cfg: PipelineConfig, pool) -> BatchOutcome:
    """Prepare, embed, commit and index one claimed batch. Never raises for item errors."""
    outcome = BatchOutcome()
    results = [f.result() for f in [pool.submit(prepare_item, item, cfg) for item in items]]
    prepared = [r for r in results if isinstance(r, PreparedItem)]
    outcome.failures = [r for r in results if isinstance(r, ItemFailure)]

    if prepared:
        embed_failures = embed(prepared)
        if embed_failures:
            for p in prepared:
                p.discard()
            outcome.failures += embed_failures
            prepared = []

    commit: CommitResult | None = None
    if prepared:
        try:
            commit = commit_batch(prepared)
        except Exception as exc:
            logger.exception("Commit failed for %d item(s)", len(prepared))
            info = classify_ingest_error(exc, stage="db_save")
            outcome.failures += [
                ItemFailure(p.item.id, info["kind"], "db_save", info["reason"], info["detail"])
                for p in prepared
            ]
        finally:
            for p in prepared:
                p.discard()  # no-op for files already placed

    record_failures(outcome.failures)
    system = [f for f in outcome.failures if f.kind == KIND_SYSTEM]
    outcome.system_reason = system[0].reason if system else None

    if commit is not None:
        write_vectors(commit.done)
        for c in commit.done:
            remove_staged(c.prepared.item.job_id, c.prepared.item.staging_key)
        outcome.done = len(commit.done)
        outcome.duplicates = len(commit.duplicates)

    logger.info(
        "Ingest batch: %d done, %d duplicate, %d failed",
        outcome.done,
        outcome.duplicates,
        len(outcome.failures),
    )
    return outcome

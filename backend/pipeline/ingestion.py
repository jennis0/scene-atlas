"""Main image ingestion pipeline.

Functions:
    analyse_upload       — Parse and group uploaded files for the preview UI
    process_import_group — Process a confirmed group (batched pipeline)
    process_single_image — Process one image (thin wrapper for single-image use)
    bulk_image_ingestion — CLI batch ingestion from directories (batched pipeline)
    prepare_single_image — Parse, copy, thumbnail, colors for one image
"""

import gc
import hashlib
import json
import logging
import resource
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import (
    Color,
    Image,
    ImageGroup,
    ImportGroupJob,
    ImportJob,
    Tag,
    TagCategory,
    get_engine,
    get_session_local,
)
from backend.app.services import (
    ImageParser,
    get_image_store,
    get_qdrant_service,
    get_thumbnail_store,
)
from backend.app.services.fts_service import fts_rebuild
from backend.app.services.image_parser import build_search_text

from .error_classifier import classify_ingest_error
from .pipeline_config import PipelineConfig, load_pipeline_config
from .tasks.embedding_generation import (
    batch_generate_clip_embeddings,
    generate_clip_embedding,
)

# ---------------------------------------------------------------------------
# Helper: Build parser with tag vocabulary
# ---------------------------------------------------------------------------


def _build_parser() -> ImageParser:
    """Create an ImageParser with tag vocabulary loaded from DB."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        categories = db.query(TagCategory).all()
        cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
        return ImageParser(tag_categories=cat_dicts)
    finally:
        db.close()


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file, reading in 8KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Helper: Save one image dict to DB (shared logic for single and batch)
# ---------------------------------------------------------------------------


def _save_image_to_db(db: Session, image_data: dict) -> int:
    """Save one image and its tags/colors to the database within an existing session.

    Always creates a new record (never updates an existing one by storage_key,
    since multiple records can now share the same storage_key for dedup).

    Returns the image ID. Does NOT commit — caller must commit.
    """
    image = Image(
        filename=image_data["filename"],
        storage_key=image_data["storage_key"],
        name=image_data["name"],
        author=image_data.get("author"),
        width=image_data["width"],
        height=image_data["height"],
        file_size=image_data["file_size"],
        thumbnail_key=image_data.get("thumbnail_key"),
        gridded=image_data.get("gridded"),
        grid_width=image_data.get("grid_width"),
        grid_height=image_data.get("grid_height"),
        grid_type=image_data.get("grid_type"),
        grid_confidence=image_data.get("grid_confidence"),
        subgroup=image_data.get("subgroup"),
        image_type=image_data.get("image_type", "battlemap"),
        content_hash=image_data.get("content_hash"),
        media_type=image_data.get("media_type", "image"),
        needs_review=image_data.get("needs_review", False),
        import_job_id=image_data.get("import_job_id"),
        search_text=build_search_text(
            name=image_data.get("name"),
            filename=image_data.get("filename"),
            author=image_data.get("author"),
            tags=image_data.get("tags"),
            subgroup=image_data.get("subgroup"),
        ),
    )
    db.add(image)
    db.flush()

    # Handle group
    group_name = image_data.get("group_name")
    author = image_data.get("author")
    if group_name:
        grp = (
            db.query(ImageGroup)
            .filter(
                ImageGroup.base_name == group_name,
                ImageGroup.author == author,
            )
            .first()
        )
        if not grp:
            grp = ImageGroup(base_name=group_name, author=author)
            db.add(grp)
            db.flush()
        image.group_id = grp.id

    # Add tags
    for tag_data in image_data.get("tags", []):
        db.add(
            Tag(
                image_id=image.id,
                category=tag_data["category"],
                value=tag_data["value"],
                confidence=tag_data.get("confidence", 1.0),
                source=tag_data.get("source", "auto"),
            )
        )

    # Add colors
    for color_data in image_data.get("colors", []):
        db.add(
            Color(
                image_id=image.id,
                color_hex=color_data["color_hex"],
                percentage=color_data["percentage"],
                color_order=color_data["color_order"],
            )
        )

    return image.id


# ---------------------------------------------------------------------------
# Core tasks
# ---------------------------------------------------------------------------


def scan_directory(directory: str) -> list[str]:
    """Scan directory for supported image files."""
    logger = logging.getLogger(__name__)
    directory_obj = Path(directory)
    logger.info("Scanning directory: %s", directory_obj)
    image_paths = []

    for ext in settings.all_supported_formats:
        for path in directory_obj.rglob(f"*{ext}"):
            if "__MACOSX" in path.parts or path.name.startswith("._"):
                continue
            image_paths.append(str(path))

    logger.info("Found %s images/videos in %s", len(image_paths), directory_obj)
    return image_paths


def prepare_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
    parser: ImageParser | None = None,
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Prepare a single image: parse metadata, copy to store, thumbnails, colors.

    This task handles everything EXCEPT CLIP embedding and database/Qdrant saves,
    which are batched separately for better throughput.

    Runs inline (not sub-tasks) for minimal overhead when submitted concurrently.

    Args:
        image_path: Absolute path to the image file
        source_dir: Root directory for relative path parsing (CLI mode)
        metadata: Explicit metadata dict (web import mode)
        parser: Pre-built ImageParser (avoids rebuilding per image in batch)

    Returns:
        Dict with 'status', 'image_data', 'original_image_path', 'qdrant_metadata'
    """
    logger = logging.getLogger(__name__)
    image_path_obj = Path(image_path)
    logger.info("Preparing image: %s", image_path_obj.name)

    stage = "parse"
    try:
        # --- Parse metadata ---
        if metadata:
            author = metadata.get("author")
            group_name = metadata.get("group_name")
            name = metadata.get("name") or group_name
            subgroup = metadata.get("subgroup")
            image_type = metadata.get("image_type", "battlemap")
            gridded = metadata.get("gridded")
            grid_width = metadata.get("grid_width")
            grid_height = metadata.get("grid_height")
            grid_type = metadata.get("grid_type")
            tags = metadata.get("tags", [])
            content_hash = metadata.get("content_hash")
            reuse_storage_key = metadata.get("reuse_storage_key")
            reuse_thumbnail_key = metadata.get("reuse_thumbnail_key")
            needs_review = metadata.get("needs_review", False)
            import_job_id = metadata.get("import_job_id")
        else:
            if parser is None:
                parser = _build_parser()
            source_dir_obj = Path(source_dir) if source_dir else None
            if source_dir_obj:
                relative = image_path_obj.relative_to(source_dir_obj)
            else:
                relative = Path(image_path_obj.name)
            parsed = parser.parse(str(relative))
            author = parsed["author"]
            group_name = parsed["group_name"]
            name = parsed.get("name") or group_name
            subgroup = parsed["subgroup"]
            image_type = parsed.get("image_type", "battlemap")
            gridded = parsed["gridded"]
            grid_width = parsed["grid_width"]
            grid_height = parsed["grid_height"]
            grid_type = parsed.get("grid_type")
            tags = parsed["tags"]
            content_hash = None
            reuse_storage_key = None
            reuse_thumbnail_key = None
            needs_review = False
            import_job_id = None

        # --- Duplicate reuse path ---
        # If we're reusing an existing file, skip copy/thumbnail/color extraction
        # and copy properties from the existing image record instead.
        if reuse_storage_key:
            image_store = get_image_store()
            if not image_store.get_path(reuse_storage_key).exists():
                logger.warning(
                    "Reuse key %s not found on disk, falling back to normal path", reuse_storage_key
                )
                reuse_storage_key = None  # Fall through to normal path below

        if reuse_storage_key:
            # Look up existing image to copy dimensions, file_size, colors
            engine = get_engine(settings.database_url)
            SessionLocal = get_session_local(engine)
            db = SessionLocal()
            try:
                source_image = (
                    db.query(Image).filter(Image.storage_key == reuse_storage_key).first()
                )
                if source_image:
                    width = source_image.width
                    height = source_image.height
                    file_size = source_image.file_size
                    colors = [
                        {
                            "color_hex": c.color_hex,
                            "percentage": c.percentage,
                            "color_order": c.color_order,
                        }
                        for c in source_image.colors
                    ]
                    reuse_embedding_from = source_image.id
                else:
                    # Source record gone — fall back to computing from file
                    logger.warning("No DB record for storage_key=%s", reuse_storage_key)
                    reuse_storage_key = None
            finally:
                db.close()

        if reuse_storage_key:
            reuse_ext = image_path_obj.suffix.lower()
            image_data = {
                "filename": image_path_obj.name,
                "storage_key": reuse_storage_key,
                "name": name,
                "author": author,
                "group_name": group_name,
                "width": width,
                "height": height,
                "file_size": file_size,
                "thumbnail_key": reuse_thumbnail_key,
                "gridded": gridded,
                "grid_width": grid_width,
                "grid_height": grid_height,
                "grid_type": metadata.get("grid_type") if metadata else None,
                "grid_confidence": metadata.get("grid_confidence") if metadata else None,
                "subgroup": subgroup,
                "image_type": image_type,
                "content_hash": content_hash,
                "media_type": "video" if reuse_ext in settings.supported_video_formats else "image",
                "needs_review": needs_review,
                "tags": tags,
                "colors": colors,
                "import_job_id": import_job_id,
            }

            qdrant_metadata = {
                "filename": image_path_obj.name,
                "author": author,
                "base_name": group_name,
            }

            return {
                "status": "success",
                "image_data": image_data,
                "original_image_path": image_path,
                "qdrant_metadata": qdrant_metadata,
                "reuse_embedding_from": reuse_embedding_from,
            }

        # --- Normal path: Copy image/video into ImageStore ---
        stage = "copy"
        image_store = get_image_store()
        storage_key_stem = uuid.uuid4().hex[:12]
        ext = image_path_obj.suffix.lower()
        storage_key = f"{storage_key_stem}{ext}"
        image_store.put(storage_key, image_path_obj)

        # Compute content hash if not already known
        if not content_hash:
            content_hash = _compute_file_hash(image_path_obj)

        # --- File size (inline, fast) ---
        file_size = image_path_obj.stat().st_size

        # --- Generate thumbnails + get dimensions ---
        # --- Extract colors ---
        stage = "thumbnails"
        from backend.pipeline.tasks.color_extraction import (
            extract_dominant_colors as _extract_colors,
        )
        from backend.pipeline.tasks.image_processing import generate_thumbnails as _gen_thumbs

        is_video = ext in settings.supported_video_formats

        if is_video:
            # Extract first frame to a temp JPEG for thumbnail/color/CLIP processing
            from backend.app.services.video_utils import extract_first_frame, get_video_dimensions

            frame_img = extract_first_frame(image_path_obj)
            frame_path = image_path_obj.parent / f".{storage_key_stem}_frame.jpg"
            frame_img.save(str(frame_path), format="JPEG", quality=95)
            frame_img.close()

            thumbnail_result = _gen_thumbs(str(frame_path), storage_key_stem)
            thumbnail_keys = thumbnail_result["keys"]
            stage = "colors"
            colors = _extract_colors(str(frame_path), pipeline_config=pipeline_config)
            width, height = get_video_dimensions(image_path_obj)
            clip_image_path = str(frame_path)  # keep alive for CLIP in _process_batch
        else:
            thumbnail_result = _gen_thumbs(image_path, storage_key_stem)
            thumbnail_keys = thumbnail_result["keys"]
            stage = "colors"
            colors = _extract_colors(image_path, pipeline_config=pipeline_config)
            width, height = thumbnail_result["dimensions"]
            clip_image_path = None

        thumbnail_key = thumbnail_keys.get("medium", thumbnail_keys.get("small"))

        # Use the medium (or small) thumbnail as the CLIP encoding source.
        # CLIP resizes to 224×224 internally, so opening full-res originals is wasteful.
        # Thumbnails are ~470KB vs potentially 50-200MB for originals.
        # clip_image_path retains its original meaning: temp video frame to clean up after CLIP.
        if is_video:
            clip_source_path = str(frame_path)  # same file as clip_image_path
        else:
            clip_source_path = (
                str(get_thumbnail_store().get_path(thumbnail_key)) if thumbnail_key else None
            )

        # --- Image-based grid detection (optional, battlemaps only) ---
        stage = "grid_detection"
        # grid_type is already set from metadata or filename parsing above.
        # Image-based detection can override it if it produces a result.
        grid_confidence = None

        _cfg = pipeline_config  # may be None — detect_grid_from_image handles both
        _grid_enabled = (
            _cfg.enable_image_grid_detection
            if _cfg is not None
            else False  # safe default; callers should always pass a config
        )

        if _grid_enabled and image_type == "battlemap" and not is_video:
            from backend.pipeline.tasks.grid_detection import (
                detect_grid_from_image as _detect_grid,
            )

            if gridded is None:
                # No filename hint — detect presence + size
                grid_result = _detect_grid(
                    image_path, width, height, size_only=False, pipeline_config=_cfg
                )
            elif gridded is True and grid_width is None:
                # Filename says gridded but no dimensions — detect size only
                grid_result = _detect_grid(
                    image_path, width, height, size_only=True, pipeline_config=_cfg
                )
            else:
                grid_result = None

            if grid_result and grid_result.get("confidence", 0) > 0:
                if gridded is None:
                    gridded = grid_result.get("gridded")
                if grid_result.get("grid_width") is not None:
                    grid_width = grid_result["grid_width"]
                    grid_height = grid_result["grid_height"]
                grid_type = grid_result.get("grid_type")
                grid_confidence = grid_result.get("confidence")

        # --- Build result ---
        image_data = {
            "filename": image_path_obj.name,
            "storage_key": storage_key,
            "name": name,
            "author": author,
            "group_name": group_name,
            "width": width,
            "height": height,
            "file_size": file_size,
            "thumbnail_key": thumbnail_key,
            "gridded": gridded,
            "grid_width": grid_width,
            "grid_height": grid_height,
            "grid_type": grid_type,
            "grid_confidence": grid_confidence,
            "subgroup": subgroup,
            "image_type": image_type,
            "content_hash": content_hash,
            "media_type": "video" if is_video else "image",
            "needs_review": needs_review,
            "tags": tags,
            "colors": colors,
            "import_job_id": import_job_id,
        }

        qdrant_metadata = {
            "filename": image_path_obj.name,
            "author": author,
            "base_name": group_name,
        }

        return {
            "status": "success",
            "image_data": image_data,
            "original_image_path": image_path,
            "clip_image_path": clip_image_path,  # None for images, temp frame path for videos (cleanup only)
            "clip_source_path": clip_source_path,  # thumbnail path for CLIP encoding (avoids full-res loads)
            "qdrant_metadata": qdrant_metadata,
        }

    except Exception as e:
        logger.exception("Failed to prepare image %s at stage '%s'", image_path_obj, stage)
        error_info = classify_ingest_error(e, stage=stage)
        return {
            "status": "failed",
            "original_image_path": image_path,
            "error": error_info["reason"],
            "error_info": error_info,
        }


# ---------------------------------------------------------------------------
# Single-image save tasks (kept for process_single_image wrapper)
# ---------------------------------------------------------------------------


def save_to_database(image_data: dict) -> int:
    """Save image and related data to SQLite database.

    Returns:
        Image ID
    """
    logger = logging.getLogger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        image_id = _save_image_to_db(db, image_data)
        db.commit()
        logger.info("Saved image to database: %s (ID: %s)", image_data["filename"], image_id)
        return image_id
    except Exception as e:
        db.rollback()
        logger.error("Error saving to database: %s", e)
        raise
    finally:
        db.close()


def save_to_qdrant(image_id: int, embedding: list[float], metadata: dict) -> bool:
    """Save embedding to Qdrant."""
    logger = logging.getLogger(__name__)
    try:
        success = get_qdrant_service().add_image_embedding(
            image_id=image_id,
            embedding=embedding,
            metadata=metadata,
        )
        if success:
            logger.info("Saved embedding to Qdrant for image_id=%s", image_id)
        return success
    except Exception as e:
        logger.error("Error saving to Qdrant: %s", e)
        raise


# ---------------------------------------------------------------------------
# Batch save tasks
# ---------------------------------------------------------------------------


def batch_save_to_database(image_data_list: list[dict]) -> list[int]:
    """Save multiple images to the database in a single transaction.

    Args:
        image_data_list: List of image data dicts

    Returns:
        List of image IDs
    """
    logger = logging.getLogger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        image_ids = []
        for image_data in image_data_list:
            image_id = _save_image_to_db(db, image_data)
            image_ids.append(image_id)
        db.commit()
        logger.info("Batch saved %s images to database", len(image_ids))
        return image_ids
    except Exception as e:
        db.rollback()
        logger.error("Error batch saving to database: %s", e)
        raise
    finally:
        db.close()


def batch_save_to_qdrant(items: list[dict]) -> bool:
    """Save multiple embeddings to Qdrant in one call.

    Qdrant is the semantic search index, not the source of truth.  A failure
    here is non-fatal: images are already safely committed to SQLite and remain
    searchable via FTS/filters.  We log a warning and return False rather than
    raising so the ingestion pipeline does not roll back committed DB records.

    Args:
        items: List of dicts with 'image_id', 'embedding', 'metadata'

    Returns:
        True if successful, False on error
    """
    logger = logging.getLogger(__name__)
    try:
        success = get_qdrant_service().batch_add_embeddings(items)
        if success:
            logger.info("Batch saved %s embeddings to Qdrant", len(items))
        return success
    except Exception as e:
        logger.warning(
            "Qdrant batch save failed (non-fatal — %s embeddings not indexed): %s", len(items), e
        )
        return False


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------


def update_import_group_job_progress(
    group_job_id: str,
    processed: int,
    failed: int,
    status: str = "running",
    created_group_id: int | None = None,
    file_errors: list[dict] | None = None,
) -> None:
    """Update ImportGroupJob progress counters in the database."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        group_job = db.query(ImportGroupJob).filter(ImportGroupJob.id == group_job_id).first()
        if group_job:
            group_job.processed_files = processed
            group_job.failed_files = failed
            group_job.status = status
            if created_group_id is not None:
                group_job.created_group_id = created_group_id
            if file_errors:
                group_job.file_errors = json.dumps(file_errors)
            if status == "completed":
                group_job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Batch processing helper
# ---------------------------------------------------------------------------


def _process_batch(
    prepared_results: list[dict],
) -> tuple[list[dict], int]:
    """Process a batch of prepared images: CLIP embed, DB save, Qdrant save.

    Handles two kinds of successful results:
    - New images: need CLIP embedding generation
    - Reuse images: retrieve existing embedding from Qdrant (or fall back to
      generating from the stored file if retrieval fails)

    Args:
        prepared_results: List of results from prepare_single_image

    Returns:
        Tuple of (all_results including failures, count of batch failures)
    """
    logger = logging.getLogger(__name__)
    # Separate successes from failures
    successful = [r for r in prepared_results if r["status"] == "success"]
    batch_failed = len(prepared_results) - len(successful)

    if not successful:
        return prepared_results, batch_failed

    # Split into new images vs reuse images
    new_images = [r for r in successful if "reuse_embedding_from" not in r]
    reuse_images = [r for r in successful if "reuse_embedding_from" in r]

    # --- New images: batch CLIP embedding ---
    # Use clip_source_path (thumbnail for images, first-frame JPEG for videos).
    # clip_image_path is now only used for cleanup of temp video frames below.
    if new_images:
        image_paths = [r.get("clip_source_path") or r["original_image_path"] for r in new_images]
        try:
            embeddings = batch_generate_clip_embeddings(image_paths)
            for prep, embedding in zip(new_images, embeddings, strict=True):
                prep["embedding"] = embedding
        except Exception as clip_exc:
            logger.exception("Batch CLIP embedding failed for %d images", len(new_images))
            error_info = classify_ingest_error(clip_exc, stage="embedding")
            for prep in new_images:
                prep["status"] = "failed"
                prep["error"] = error_info["reason"]
                prep["error_info"] = error_info
                batch_failed += 1
        finally:
            # Clean up temp video frame files whether or not CLIP succeeded
            for prep in new_images:
                if prep.get("clip_image_path"):
                    Path(prep["clip_image_path"]).unlink(missing_ok=True)

    # --- Reuse images: retrieve existing embeddings from Qdrant ---
    for prep in reuse_images:
        source_id = prep["reuse_embedding_from"]
        embedding = get_qdrant_service().get_embedding(source_id)
        if embedding:
            prep["embedding"] = embedding
        else:
            # Fallback: generate from the stored file
            logger.warning(
                "Could not retrieve embedding for source image %s, generating from stored file",
                source_id,
            )
            stored_path = get_image_store().get_path(prep["image_data"]["storage_key"])
            if stored_path.exists():
                prep["embedding"] = generate_clip_embedding(str(stored_path))
            else:
                logger.error("Stored file not found for reuse: %s", stored_path)
                error_info = classify_ingest_error(
                    FileNotFoundError(f"Stored file not found: {stored_path}"),
                    stage="embedding",
                )
                prep["status"] = "failed"
                prep["error"] = error_info["reason"]
                prep["error_info"] = error_info
                batch_failed += 1

    # Re-filter to only truly successful results
    all_successful = [r for r in successful if r["status"] == "success"]

    # Batch DB save — isolated so a failure doesn't kill subsequent batches
    image_ids: list[int] = []
    if all_successful:
        image_data_list = [r["image_data"] for r in all_successful]
        try:
            image_ids = batch_save_to_database(image_data_list)
        except Exception as db_exc:
            logger.exception("Batch DB save failed for %d images", len(all_successful))
            error_info = classify_ingest_error(db_exc, stage="db_save")
            for prep in all_successful:
                prep["status"] = "failed"
                prep["error"] = error_info["reason"]
                prep["error_info"] = error_info
                batch_failed += 1
            all_successful = []

    # Batch Qdrant save (only if DB save succeeded)
    if all_successful and image_ids:
        qdrant_items = [
            {
                "image_id": image_id,
                "embedding": prep["embedding"],
                "metadata": prep["qdrant_metadata"],
            }
            for image_id, prep in zip(image_ids, all_successful, strict=True)
        ]
        batch_save_to_qdrant(qdrant_items)

        # Attach image IDs to results
        for prep, image_id in zip(all_successful, image_ids, strict=True):
            prep["image_id"] = image_id

    return prepared_results, batch_failed


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


def process_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Process a single image end-to-end.

    Thin wrapper around prepare_single_image + single CLIP + single DB/Qdrant save.
    Used for one-off processing; batch flows use the batched pipeline directly.
    """
    logger = logging.getLogger(__name__)
    image_path_obj = Path(image_path)
    logger.info("Processing image: %s", image_path_obj)
    stage = "prepare"

    try:
        # Prepare (thumbnails, colors, copy to store)
        prepared = prepare_single_image(image_path, source_dir=source_dir, metadata=metadata)

        if prepared["status"] != "success":
            return {
                "status": "failed",
                "filepath": image_path,
                "error": prepared.get("error", "Preparation failed"),
            }

        # CLIP embedding (single image)
        stage = "embedding"
        embedding = generate_clip_embedding(image_path)

        # Save to database
        stage = "db_save"
        image_id = save_to_database(prepared["image_data"])

        # Save to Qdrant
        stage = "qdrant_save"
        save_to_qdrant(
            image_id=image_id,
            embedding=embedding,
            metadata=prepared["qdrant_metadata"],
        )

        logger.info("Successfully processed image: %s", image_path_obj)
        return {
            "status": "success",
            "image_id": image_id,
            "filepath": image_path,
        }

    except Exception as e:
        logger.exception("Failed to process image %s", image_path_obj)
        error_info = classify_ingest_error(e, stage=stage)
        return {
            "status": "failed",
            "filepath": image_path,
            "error": error_info["reason"],
        }


def bulk_image_ingestion(
    source_dirs: list[str],
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Ingest images from multiple directories using batched pipeline.

    Images are processed in batches for maximum throughput:
    - prepare_single_image tasks run concurrently via .submit()
    - CLIP embeddings are generated in batch (vectorized forward pass)
    - Database and Qdrant saves are batched into single transactions
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    batch_size = pipeline_config.ingestion_batch_size
    logger.info(
        "Starting bulk ingestion from %s directories (batch_size=%s)", len(source_dirs), batch_size
    )

    successful = 0
    failed = 0
    total_images = 0
    concurrency = pipeline_config.max_concurrent_prepare

    # Build parser once for all images (avoids per-image DB query)
    parser = _build_parser()

    for dir_path in source_dirs:
        directory = Path(dir_path)
        if not directory.exists():
            logger.warning("Directory does not exist: %s", directory)
            continue

        image_paths = scan_directory(dir_path)
        total_images += len(image_paths)

        # Process in batches
        for batch_start in range(0, len(image_paths), batch_size):
            batch = image_paths[batch_start : batch_start + batch_size]
            logger.info(
                "Processing batch %s (%s images, %s/%s)",
                batch_start // batch_size + 1,
                len(batch),
                batch_start + len(batch),
                len(image_paths),
            )

            # Step 1: Prepare images with bounded concurrency to control memory usage.
            prepared_results = []
            with ThreadPoolExecutor(max_workers=concurrency) as prep_pool:
                futures = [
                    prep_pool.submit(
                        prepare_single_image,
                        image_path=img_path,
                        source_dir=dir_path,
                        parser=parser,
                        pipeline_config=pipeline_config,
                    )
                    for img_path in batch
                ]
                prepared_results = [f.result() for f in futures]

            # Step 2-4: Batch CLIP → batch DB save → batch Qdrant save
            batch_results, _ = _process_batch(prepared_results)
            successful += sum(1 for r in batch_results if r["status"] == "success")
            failed += sum(1 for r in batch_results if r["status"] != "success")

    summary = {
        "total_images": total_images,
        "processed": successful + failed,
        "successful": successful,
        "failed": failed,
    }

    # Rebuild FTS index after bulk import
    if successful > 0:
        try:
            engine = get_engine(settings.database_url)
            SessionLocal = get_session_local(engine)
            db_fts = SessionLocal()
            try:
                fts_rebuild(db_fts)
                logger.info("FTS index rebuilt after bulk ingestion")
            finally:
                db_fts.close()
        except Exception as e:
            logger.warning("FTS rebuild failed (non-fatal): %s", e)

    logger.info("Bulk ingestion complete: %s successful, %s failed", successful, failed)
    return summary


def analyse_upload(
    staging_dir: str,
    relative_paths: list[str],
    precomputed_hashes: dict[str, dict] | None = None,
    default_image_type: str = "battlemap",
) -> list[dict]:
    """Parse and group uploaded files for the preview UI.

    Also computes SHA-256 content hashes for each file and checks the
    database for existing images with matching hashes (duplicate detection).

    If ``precomputed_hashes`` is provided (from the client-side pre-flight
    check), those entries skip server-side hash computation and duplicate
    lookup — their content_hash and duplicate_of are used directly.

    ``default_image_type`` is passed to the parser so it can apply
    type-specific parsing rules (e.g. skip grid detection for scenes).
    """
    logger = logging.getLogger(__name__)
    logger.info("Analysing %s uploaded files in %s", len(relative_paths), staging_dir)
    staging = Path(staging_dir)
    if precomputed_hashes is None:
        precomputed_hashes = {}

    parser = _build_parser()
    groups = parser.group_files(relative_paths, image_type=default_image_type)

    # Compute content hashes and detect duplicates
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        # Collect hashes that still need DB lookup (non-precomputed files)
        hashes_to_check: dict[str, list[dict]] = {}  # hash -> [file_entry, ...]

        for group in groups:
            for file_entry in group["files"]:
                rel_path = file_entry["relative_path"]

                # Use precomputed data if available (from client-side check)
                precomputed = precomputed_hashes.get(rel_path)
                if precomputed:
                    file_entry["content_hash"] = precomputed["content_hash"]
                    if precomputed.get("duplicate_of"):
                        file_entry["duplicate_of"] = precomputed["duplicate_of"]
                    continue

                # Compute hash for files actually in staging
                file_path = staging / rel_path
                if not file_path.exists():
                    continue

                content_hash = _compute_file_hash(file_path)
                file_entry["content_hash"] = content_hash
                hashes_to_check.setdefault(content_hash, []).append(file_entry)

        # Batch-query DB for any server-computed hashes
        if hashes_to_check:
            all_hashes = list(hashes_to_check.keys())
            existing_images = db.query(Image).filter(Image.content_hash.in_(all_hashes)).all()
            hash_to_image: dict[str, Image] = {}
            for img in existing_images:
                if img.content_hash and img.content_hash not in hash_to_image:
                    hash_to_image[img.content_hash] = img

            for h, entries in hashes_to_check.items():
                existing = hash_to_image.get(h)
                if existing:
                    dup_info = {
                        "image_id": existing.id,
                        "name": existing.name,
                        "author": existing.author,
                        "storage_key": existing.storage_key,
                        "thumbnail_key": existing.thumbnail_key,
                        "group_name": existing.group_name,
                    }
                    for entry in entries:
                        entry["duplicate_of"] = dup_info
                    logger.info(
                        "  Duplicate detected: %s file(s) match image %s (%s)",
                        len(entries),
                        existing.id,
                        existing.name,
                    )
    finally:
        db.close()

    logger.info("Detected %s group(s)", len(groups))
    for g in groups:
        logger.info("  %s / %s (%s files)", g.get("author", "?"), g["group_name"], len(g["files"]))

    return groups


# ---------------------------------------------------------------------------
# Shared group-processing helper (used by both single-group and job flows)
# ---------------------------------------------------------------------------


def _run_group(
    group_job_id: str,
    staging_dir: str,
    author: str,
    group_name: str,
    files: list[dict],
    pipeline_config: PipelineConfig | None = None,
    needs_review: bool = False,
    job_id: str | None = None,
) -> tuple[int, int]:
    """Process one group end-to-end and return (processed, failed) counts.

    Updates ImportGroupJob progress after every batch and marks it completed (or
    failed) when done.
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    batch_size = pipeline_config.ingestion_batch_size
    concurrency = pipeline_config.max_concurrent_prepare
    staging = Path(staging_dir)
    processed = 0
    failed = 0
    all_file_errors: list[dict] = []

    logger.info(
        "Starting group '%s' by '%s' (%d files, batch_size=%d, concurrency=%d)",
        group_name,
        author,
        len(files),
        batch_size,
        concurrency,
    )

    # Filter to files that exist in staging or have a reuse key (duplicate not uploaded)
    valid_files = []
    for file_info in files:
        image_path = staging / file_info["relative_path"]
        if image_path.exists():
            valid_files.append((file_info, str(image_path)))
        elif file_info.get("reuse_storage_key"):
            # Duplicate not in staging — prepare_single_image only uses
            # image_path_obj.name for the filename in the reuse path
            valid_files.append((file_info, str(image_path)))
        else:
            logger.warning("File not found in staging: %s", image_path)
            failed += 1
            all_file_errors.append(
                {
                    "filename": image_path.name,
                    "reason": "File was not found in staging",
                    "stage": "copy",
                }
            )

    if failed > 0:
        update_import_group_job_progress(
            group_job_id, processed, failed, file_errors=all_file_errors
        )

    try:
        for batch_start in range(0, len(valid_files), batch_size):
            batch = valid_files[batch_start : batch_start + batch_size]
            logger.info(
                "[%s] batch %s (%s images, %s/%s)",
                group_name,
                batch_start // batch_size + 1,
                len(batch),
                batch_start + len(batch),
                len(valid_files),
            )

            # Prepare images with bounded concurrency to control peak memory use.
            import time as _time

            _t0 = _time.monotonic()
            with ThreadPoolExecutor(max_workers=concurrency) as prep_pool:
                futures = [
                    prep_pool.submit(
                        prepare_single_image,
                        image_path=image_path,
                        metadata={
                            "author": author,
                            "group_name": group_name,
                            "name": file_info.get("name") or group_name,
                            "tags": file_info.get("tags", []),
                            "gridded": file_info.get("gridded"),
                            "grid_width": file_info.get("grid_width"),
                            "grid_height": file_info.get("grid_height"),
                            "grid_type": file_info.get("grid_type"),
                            "subgroup": file_info.get("subgroup"),
                            "image_type": file_info.get("image_type", "battlemap"),
                            "content_hash": file_info.get("content_hash"),
                            "media_type": file_info.get("media_type"),
                            "reuse_storage_key": file_info.get("reuse_storage_key"),
                            "reuse_thumbnail_key": file_info.get("reuse_thumbnail_key"),
                            "needs_review": needs_review,
                            "import_job_id": job_id,
                        },
                        pipeline_config=pipeline_config,
                    )
                    for file_info, image_path in batch
                ]
                prepared_results = [f.result() for f in futures]
            _t_prepare = _time.monotonic() - _t0
            logger.info("[%s] prepare took %.1fs", group_name, _t_prepare)

            # Batch CLIP → batch DB → batch Qdrant
            _t0 = _time.monotonic()
            batch_results, _ = _process_batch(prepared_results)
            _t_process = _time.monotonic() - _t0
            logger.info("[%s] process_batch took %.1fs", group_name, _t_process)
            batch_success = sum(1 for r in batch_results if r["status"] == "success")
            processed += batch_success
            failed += len(batch_results) - batch_success

            # Collect per-file errors from this batch
            for r in batch_results:
                if r["status"] == "failed":
                    error_info = r.get("error_info", {})
                    all_file_errors.append(
                        {
                            "filename": Path(r.get("original_image_path", "unknown")).name,
                            "reason": error_info.get("reason", r.get("error", "Unknown error")),
                            "stage": error_info.get("stage", "unknown"),
                        }
                    )

            update_import_group_job_progress(
                group_job_id, processed, failed, file_errors=all_file_errors
            )

            # Free PIL / numpy / torch objects that survived refcount collection
            gc.collect()
            # Force glibc to return freed pages to the OS.  Without this,
            # Python's pymalloc + glibc malloc retain large arenas even after
            # the Python objects are freed, causing RSS to stay inflated.
            try:
                import ctypes

                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass  # non-Linux or libc unavailable — no-op
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            logger.info(
                "[%s] batch %d complete — RSS: %.0f MB",
                group_name,
                batch_start // batch_size + 1,
                rss_mb,
            )

        # Look up the ImageGroup that was created/updated so we can link back to it
        _created_group_id: int | None = None
        try:
            _engine = get_engine(settings.database_url)
            _Session = get_session_local(_engine)
            _db = _Session()
            try:
                grp = (
                    _db.query(ImageGroup)
                    .filter(ImageGroup.base_name == group_name, ImageGroup.author == author)
                    .first()
                )
                if grp:
                    _created_group_id = grp.id
            finally:
                _db.close()
        except Exception:
            pass  # Non-fatal — link is a convenience, not required

        update_import_group_job_progress(
            group_job_id,
            processed,
            failed,
            status="completed",
            created_group_id=_created_group_id,
            file_errors=all_file_errors,
        )
        logger.info("Group %s (%s): %s ok, %s failed", group_job_id, group_name, processed, failed)
    except Exception:
        # Count all files not yet processed as failed, mark group as failed
        remaining = len(valid_files) - processed - failed
        failed += remaining
        logger.exception(
            "Group %s (%s) failed after %s images processed", group_job_id, group_name, processed
        )
        update_import_group_job_progress(
            group_job_id, processed, failed, status="failed", file_errors=all_file_errors
        )
        raise  # re-raise so process_import_job can catch it per-group

    return processed, failed


def _mark_group_job_failed(group_job_id: str, error_message: str) -> None:
    """Mark an ImportGroupJob as failed with an error message.

    Non-fatal: any DB error is logged and swallowed so it never propagates
    to the caller (which is already handling a failure scenario).
    """
    logger = logging.getLogger(__name__)
    try:
        engine = get_engine(settings.database_url)
        SessionLocal = get_session_local(engine)
        db = SessionLocal()
        try:
            group_job = db.query(ImportGroupJob).filter(ImportGroupJob.id == group_job_id).first()
            if group_job:
                group_job.status = "failed"
                group_job.error_message = error_message[:500] if error_message else None
                group_job.completed_at = datetime.now(UTC).replace(tzinfo=None)
                db.commit()
                logger.info("Marked group job %s as failed", group_job_id)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not mark group job %s as failed: %s", group_job_id, e)


def _finalize_import_job(job_id: str) -> None:
    """Update ImportJob status after a group finishes processing.

    For the confirm-all path (all_confirmed=True), delegates to
    transition_job_status() to auto-complete the job when all groups finish.

    For the single-confirm path (all_confirmed=False), does NOT auto-complete
    the job — it stays 'active' until the user explicitly calls /finalize.
    Only the running→active and all-terminal→awaiting_input transitions are
    applied in this path.

    If the job was cancelled while a group was still running, performs a
    best-effort cleanup sweep to delete any images added after the initial
    cancel sweep.
    """
    from backend.app.services.import_state import GROUP_TERMINAL_STATUSES, transition_job_status

    logger = logging.getLogger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not job:
            return

        if job.status == "cancelled":
            # Job was cancelled mid-flight — sweep for any images added after the
            # initial cancel (race condition: best-effort cleanup)
            from backend.app.api.imports import _cleanup_import_images

            swept = _cleanup_import_images(job_id, db)
            if swept:
                logger.info(
                    "Post-cancel sweep: deleted %d late-arriving image(s) for job %s",
                    swept,
                    job_id,
                )
            db.commit()
            return

        if not job.all_confirmed:
            # Single-confirm path: don't auto-complete — the job stays 'active'
            # until the user explicitly calls /finalize.  Only apply the
            # running→active and all-terminal→awaiting_input transitions.
            groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).all()
            has_running = any(g.status == "running" for g in groups)
            all_terminal = not groups or all(g.status in GROUP_TERMINAL_STATUSES for g in groups)
            now = datetime.now(UTC).replace(tzinfo=None)
            if has_running:
                job.status = "active"
                job.updated_at = now
            elif all_terminal and job.pending_groups > 0:
                job.status = "awaiting_input"
                job.updated_at = now
            # else: all submitted groups done, pending=0 → stay in current status
            db.commit()
            logger.info(
                "Import job %s stays '%s' (single-confirm, not auto-completing)",
                job_id,
                job.status,
            )
            return

        new_status = transition_job_status(db, job_id)

        if new_status == "failed":
            # Failed imports must not leave images in the DB — they would
            # cause false duplicate-hash matches when the user re-uploads.
            from backend.app.api.imports import _cleanup_import_images

            cleaned = _cleanup_import_images(job_id, db)
            if cleaned:
                logger.info(
                    "Cleaned up %d image(s) from failed import %s",
                    cleaned,
                    job_id,
                )

        db.commit()
        logger.info("Import job %s transitioned to '%s'", job_id, new_status)
    finally:
        db.close()


def _rebuild_fts() -> None:
    """Rebuild the FTS index (non-fatal on error)."""
    logger = logging.getLogger(__name__)
    try:
        engine = get_engine(settings.database_url)
        SessionLocal = get_session_local(engine)
        db = SessionLocal()
        try:
            fts_rebuild(db)
            logger.info("FTS index rebuilt successfully")
        finally:
            db.close()
    except Exception as e:
        logger.warning("FTS rebuild failed (non-fatal): %s", e)


def process_import_group(
    job_id: str,
    group_job_id: str,
    staging_dir: str,
    author: str,
    group_name: str,
    files: list[dict],
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Process a single confirmed group (single-group import path).

    For multi-group imports prefer process_import_job, which handles all groups
    in one Python process so the CLIP model is loaded only once.
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    logger.info(
        "Processing import group '%s' by '%s' (%s files) for job %s, group %s",
        group_name,
        author,
        len(files),
        job_id,
        group_job_id,
    )
    processed, failed = _run_group(
        group_job_id,
        staging_dir,
        author,
        group_name,
        files,
        pipeline_config=pipeline_config,
        needs_review=True,
        job_id=job_id,
    )
    _finalize_import_job(job_id)
    if processed > 0:
        _rebuild_fts()

    # Staging cleanup is handled by /finalize, /cancel, or expire_stale_jobs —
    # NOT here, because other groups in the same job may still be pending.

    return {
        "job_id": job_id,
        "group_job_id": group_job_id,
        "processed": processed,
        "failed": failed,
        "total": len(files),
    }


def process_import_job(
    job_id: str,
    staging_dir: str,
    groups: list[dict],
    pipeline_config: PipelineConfig | None = None,
) -> dict:
    """Process all groups for an import job in a single flow run.

    Running all groups here — rather than one flow per group — means the CLIP
    model (~600 MB) is loaded exactly once for the whole job instead of once
    per group in separate subprocesses.  Groups are processed sequentially so
    peak memory stays bounded regardless of how many groups are in the job.

    Each group dict must contain:
        group_job_id, author, group_name, files (list[dict])

    Groups are isolated: an unhandled exception in one group is caught, the
    group is marked as failed, and processing continues with the next group.
    """
    logger = logging.getLogger(__name__)
    if pipeline_config is None:
        pipeline_config = load_pipeline_config()
    logger.info("Starting import job %s: %s group(s) in %s", job_id, len(groups), staging_dir)
    total_processed = 0
    total_failed = 0

    try:
        for group in groups:
            group_job_id = group["group_job_id"]
            author = group["author"]
            group_name = group["group_name"]
            files = group["files"]
            logger.info("Processing group '%s' by '%s' (%s files)", group_name, author, len(files))
            try:
                processed, failed = _run_group(
                    group_job_id,
                    staging_dir,
                    author,
                    group_name,
                    files,
                    pipeline_config=pipeline_config,
                    needs_review=True,
                    job_id=job_id,
                )
                total_processed += processed
                total_failed += failed
            except Exception as e:
                # _run_group already updated the group job status to "failed".
                # We log the error, count all unprocessed files as failed, and
                # continue with the next group so the job doesn't abort early.
                logger.error(
                    "Group '%s' (%s) raised an unhandled exception, skipping to next group: %s",
                    group_name,
                    group_job_id,
                    e,
                )
                total_failed += len(files)
    finally:
        # Always finalize the job and rebuild FTS — even if some groups raised
        # unexpected exceptions.  Staging cleanup is handled by /finalize,
        # /cancel, or expire_stale_jobs.
        _finalize_import_job(job_id)
        if total_processed > 0:
            _rebuild_fts()

    logger.info(
        "Import job %s complete: %s processed, %s failed", job_id, total_processed, total_failed
    )
    return {
        "job_id": job_id,
        "processed": total_processed,
        "failed": total_failed,
        "total_groups": len(groups),
    }

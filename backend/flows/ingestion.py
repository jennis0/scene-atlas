"""Main image ingestion Prefect flows.

Flows:
    analyse_upload       — Parse and group uploaded files for the preview UI
    process_import_group — Process a confirmed group (batched pipeline)
    process_single_image — Process one image (thin wrapper for single-image use)
    bulk_image_ingestion — CLI batch ingestion from directories (batched pipeline)

Tasks:
    prepare_single_image         — Parse, copy, thumbnail, colors for one image
    batch_save_to_database       — Save a batch of images to SQLite in one transaction
    batch_save_to_qdrant         — Save a batch of embeddings to Qdrant in one call
    save_to_database             — Save one image to SQLite (single-image path)
    save_to_qdrant               — Save one embedding to Qdrant (single-image path)
    scan_directory               — Scan directory for supported image files
    update_import_group_job_progress — Update ImportGroupJob progress counters
"""

import hashlib
import logging  # kept for get_logger fallback
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from prefect import flow, task
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
from backend.app.services import ImageParser, get_image_store, qdrant_service
from backend.app.services.fts_service import fts_rebuild
from backend.app.services.image_parser import build_search_text

from .logger import get_logger
from .tasks.embedding_generation import (
    batch_generate_clip_embeddings,
    generate_clip_embedding,
)


# ---------------------------------------------------------------------------
# Helper: Build parser with tag vocabulary
# ---------------------------------------------------------------------------


def _build_parser() -> ImageParser:
    """Create an ImageParser with tag vocabulary loaded from DB."""
    logger = get_logger(__name__)
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
    logger = get_logger(__name__)
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


@task(name="scan_directory", retries=1)
def scan_directory(directory: str) -> list[str]:
    """Scan directory for supported image files."""
    logger = get_logger(__name__)
    directory_obj = Path(directory)
    logger.info(f"Scanning directory: {directory_obj}")
    image_paths = []

    for ext in settings.all_supported_formats:
        for path in directory_obj.rglob(f"*{ext}"):
            if "__MACOSX" in path.parts or path.name.startswith("._"):
                continue
            image_paths.append(str(path))

    logger.info(f"Found {len(image_paths)} images/videos in {directory_obj}")
    return image_paths


@task(name="prepare_single_image", retries=2)
def prepare_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
    parser: ImageParser | None = None,
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
    logger = get_logger(__name__)
    image_path_obj = Path(image_path)
    logger.info(f"Preparing image: {image_path_obj.name}")

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
            tags = metadata.get("tags", [])
            content_hash = metadata.get("content_hash")
            reuse_storage_key = metadata.get("reuse_storage_key")
            reuse_thumbnail_key = metadata.get("reuse_thumbnail_key")
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
            tags = parsed["tags"]
            content_hash = None
            reuse_storage_key = None
            reuse_thumbnail_key = None

        # --- Duplicate reuse path ---
        # If we're reusing an existing file, skip copy/thumbnail/color extraction
        # and copy properties from the existing image record instead.
        if reuse_storage_key:
            image_store = get_image_store()
            if not image_store.get_path(reuse_storage_key).exists():
                logger.warning(
                    f"Reuse key {reuse_storage_key} not found on disk, falling back to normal path"
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
                    logger.warning(f"No DB record for storage_key={reuse_storage_key}")
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
                "tags": tags,
                "colors": colors,
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
        # Call the underlying function directly (not as Prefect task) to avoid overhead
        # --- Extract colors ---
        from backend.flows.tasks.color_extraction import extract_dominant_colors as _extract_colors
        from backend.flows.tasks.image_processing import generate_thumbnails as _gen_thumbs

        is_video = ext in settings.supported_video_formats

        if is_video:
            # Extract first frame to a temp JPEG for thumbnail/color/CLIP processing
            from backend.app.services.video_utils import extract_first_frame, get_video_dimensions

            frame_img = extract_first_frame(image_path_obj)
            frame_path = image_path_obj.parent / f".{storage_key_stem}_frame.jpg"
            frame_img.save(str(frame_path), format="JPEG", quality=95)
            frame_img.close()

            thumbnail_result = _gen_thumbs.fn(str(frame_path), storage_key_stem)
            thumbnail_keys = thumbnail_result["keys"]
            colors = _extract_colors.fn(str(frame_path))
            width, height = get_video_dimensions(image_path_obj)
            clip_image_path = str(frame_path)  # keep alive for CLIP in _process_batch
        else:
            thumbnail_result = _gen_thumbs.fn(image_path, storage_key_stem)
            thumbnail_keys = thumbnail_result["keys"]
            colors = _extract_colors.fn(image_path)
            width, height = thumbnail_result["dimensions"]
            clip_image_path = None

        thumbnail_key = thumbnail_keys.get("medium", thumbnail_keys.get("small"))

        # --- Image-based grid detection (optional, battlemaps only) ---
        grid_type = None
        grid_confidence = None

        if (
            settings.enable_image_grid_detection
            and image_type == "battlemap"
            and not is_video
        ):
            from backend.flows.tasks.grid_detection import (
                detect_grid_from_image as _detect_grid,
            )

            if gridded is None:
                # No filename hint — detect presence + size
                grid_result = _detect_grid.fn(image_path, width, height, size_only=False)
            elif gridded is True and grid_width is None:
                # Filename says gridded but no dimensions — detect size only
                grid_result = _detect_grid.fn(image_path, width, height, size_only=True)
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
            "tags": tags,
            "colors": colors,
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
            "clip_image_path": clip_image_path,  # None for images, temp frame path for videos
            "qdrant_metadata": qdrant_metadata,
        }

    except Exception as e:
        logger.error(f"Failed to prepare image {image_path_obj}: {e}")
        return {
            "status": "failed",
            "original_image_path": image_path,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Single-image save tasks (kept for process_single_image wrapper)
# ---------------------------------------------------------------------------


@task(name="save_to_database", retries=2)
def save_to_database(image_data: dict) -> int:
    """Save image and related data to SQLite database.

    Returns:
        Image ID
    """
    logger = get_logger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        image_id = _save_image_to_db(db, image_data)
        db.commit()
        logger.info(f"Saved image to database: {image_data['filename']} (ID: {image_id})")
        return image_id
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving to database: {e}")
        raise
    finally:
        db.close()


@task(name="save_to_qdrant", retries=2)
def save_to_qdrant(image_id: int, embedding: list[float], metadata: dict) -> bool:
    """Save embedding to Qdrant."""
    logger = get_logger(__name__)
    try:
        success = qdrant_service.add_image_embedding(
            image_id=image_id,
            embedding=embedding,
            metadata=metadata,
        )
        if success:
            logger.info(f"Saved embedding to Qdrant for image_id={image_id}")
        return success
    except Exception as e:
        logger.error(f"Error saving to Qdrant: {e}")
        raise


# ---------------------------------------------------------------------------
# Batch save tasks
# ---------------------------------------------------------------------------


@task(name="batch_save_to_database", retries=2)
def batch_save_to_database(image_data_list: list[dict]) -> list[int]:
    """Save multiple images to the database in a single transaction.

    Args:
        image_data_list: List of image data dicts

    Returns:
        List of image IDs
    """
    logger = get_logger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        image_ids = []
        for image_data in image_data_list:
            image_id = _save_image_to_db(db, image_data)
            image_ids.append(image_id)
        db.commit()
        logger.info(f"Batch saved {len(image_ids)} images to database")
        return image_ids
    except Exception as e:
        db.rollback()
        logger.error(f"Error batch saving to database: {e}")
        raise
    finally:
        db.close()


@task(name="batch_save_to_qdrant", retries=2)
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
    logger = get_logger(__name__)
    try:
        success = qdrant_service.batch_add_embeddings(items)
        if success:
            logger.info(f"Batch saved {len(items)} embeddings to Qdrant")
        return success
    except Exception as e:
        logger.warning(
            f"Qdrant batch save failed (non-fatal — {len(items)} embeddings not indexed): {e}"
        )
        return False


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------


@task(name="update_import_group_job_progress", retries=1)
def update_import_group_job_progress(
    group_job_id: str,
    processed: int,
    failed: int,
    status: str = "running",
) -> None:
    """Update ImportGroupJob progress counters in the database."""
    logger = get_logger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        group_job = db.query(ImportGroupJob).filter(ImportGroupJob.id == group_job_id).first()
        if group_job:
            group_job.processed_files = processed
            group_job.failed_files = failed
            group_job.status = status
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
    logger = get_logger(__name__)
    # Separate successes from failures
    successful = [r for r in prepared_results if r["status"] == "success"]
    batch_failed = len(prepared_results) - len(successful)

    if not successful:
        return prepared_results, batch_failed

    # Split into new images vs reuse images
    new_images = [r for r in successful if "reuse_embedding_from" not in r]
    reuse_images = [r for r in successful if "reuse_embedding_from" in r]

    # --- New images: batch CLIP embedding ---
    # For videos, use the extracted first-frame JPEG (clip_image_path); for images use original
    if new_images:
        image_paths = [r.get("clip_image_path") or r["original_image_path"] for r in new_images]
        try:
            embeddings = batch_generate_clip_embeddings(image_paths)
            for prep, embedding in zip(new_images, embeddings, strict=True):
                prep["embedding"] = embedding
        finally:
            # Clean up temp video frame files whether or not CLIP succeeded
            for prep in new_images:
                if prep.get("clip_image_path"):
                    Path(prep["clip_image_path"]).unlink(missing_ok=True)

    # --- Reuse images: retrieve existing embeddings from Qdrant ---
    for prep in reuse_images:
        source_id = prep["reuse_embedding_from"]
        embedding = qdrant_service.get_embedding(source_id)
        if embedding:
            prep["embedding"] = embedding
        else:
            # Fallback: generate from the stored file
            logger.warning(
                f"Could not retrieve embedding for source image {source_id}, "
                f"generating from stored file"
            )
            stored_path = get_image_store().get_path(prep["image_data"]["storage_key"])
            if stored_path.exists():
                from .tasks.embedding_generation import generate_clip_embedding

                prep["embedding"] = generate_clip_embedding.fn(str(stored_path))
            else:
                logger.error(f"Stored file not found for reuse: {stored_path}")
                prep["status"] = "failed"
                prep["error"] = "Could not retrieve or generate embedding"
                batch_failed += 1

    # Re-filter to only truly successful results
    all_successful = [r for r in successful if r["status"] == "success"]

    # Batch DB save
    image_data_list = [r["image_data"] for r in all_successful]
    image_ids = batch_save_to_database(image_data_list)

    # Batch Qdrant save
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


@flow(name="process_single_image", log_prints=True)
def process_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Process a single image end-to-end.

    Thin wrapper around prepare_single_image + single CLIP + single DB/Qdrant save.
    Used for one-off processing; batch flows use the batched pipeline directly.
    """
    logger = get_logger(__name__)
    image_path_obj = Path(image_path)
    logger.info(f"Processing image: {image_path_obj}")

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
        embedding = generate_clip_embedding(image_path)

        # Save to database
        image_id = save_to_database(prepared["image_data"])

        # Save to Qdrant
        save_to_qdrant(
            image_id=image_id,
            embedding=embedding,
            metadata=prepared["qdrant_metadata"],
        )

        logger.info(f"Successfully processed image: {image_path_obj}")
        return {
            "status": "success",
            "image_id": image_id,
            "filepath": image_path,
        }

    except Exception as e:
        logger.error(f"Failed to process image {image_path_obj}: {e}")
        return {
            "status": "failed",
            "filepath": image_path,
            "error": str(e),
        }


@flow(name="bulk_image_ingestion", log_prints=True)
def bulk_image_ingestion(source_dirs: list[str]) -> dict:
    """Ingest images from multiple directories using batched pipeline.

    Images are processed in batches for maximum throughput:
    - prepare_single_image tasks run concurrently via .submit()
    - CLIP embeddings are generated in batch (vectorized forward pass)
    - Database and Qdrant saves are batched into single transactions
    """
    logger = get_logger(__name__)
    batch_size = settings.ingestion_batch_size
    logger.info(
        f"Starting bulk ingestion from {len(source_dirs)} directories (batch_size={batch_size})"
    )

    successful = 0
    failed = 0
    total_images = 0
    concurrency = settings.max_concurrent_prepare

    # Build parser once for all images (avoids per-image DB query)
    parser = _build_parser()

    for dir_path in source_dirs:
        directory = Path(dir_path)
        if not directory.exists():
            logger.warning(f"Directory does not exist: {directory}")
            continue

        image_paths = scan_directory(dir_path)
        total_images += len(image_paths)

        # Process in batches
        for batch_start in range(0, len(image_paths), batch_size):
            batch = image_paths[batch_start : batch_start + batch_size]
            logger.info(
                f"Processing batch {batch_start // batch_size + 1} "
                f"({len(batch)} images, {batch_start + len(batch)}/{len(image_paths)})"
            )

            # Step 1: Prepare images with bounded concurrency to control memory usage.
            # Submit max_concurrent_prepare tasks at a time and wait for each group
            # before submitting the next — prevents all batch images loading into RAM at once.
            prepared_results = []
            for sub_start in range(0, len(batch), concurrency):
                sub_batch = batch[sub_start : sub_start + concurrency]
                futures = [
                    prepare_single_image.submit(
                        image_path=img_path,
                        source_dir=dir_path,
                        parser=parser,
                    )
                    for img_path in sub_batch
                ]
                prepared_results.extend(f.result() for f in futures)

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
            logger.warning(f"FTS rebuild failed (non-fatal): {e}")

    logger.info(f"Bulk ingestion complete: {successful} successful, {failed} failed")
    return summary


@flow(name="analyse_upload", log_prints=True, persist_result=True)
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
    logger = get_logger(__name__)
    logger.info(f"Analysing {len(relative_paths)} uploaded files in {staging_dir}")
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
                        f"  Duplicate detected: {len(entries)} file(s) match "
                        f"image {existing.id} ({existing.name})"
                    )
    finally:
        db.close()

    logger.info(f"Detected {len(groups)} group(s)")
    for g in groups:
        logger.info(
            f"  {g.get('author', '?')} / {g['group_name']} ({len(g['files'])} files)"
        )

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
) -> tuple[int, int]:
    """Process one group end-to-end and return (processed, failed) counts.

    Updates ImportGroupJob progress after every batch and marks it completed (or
    failed) when done.  Intended to be called from a Prefect flow context.
    """
    logger = get_logger(__name__)
    batch_size = settings.ingestion_batch_size
    concurrency = settings.max_concurrent_prepare
    staging = Path(staging_dir)
    processed = 0
    failed = 0

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
            logger.warning(f"File not found in staging: {image_path}")
            failed += 1

    if failed > 0:
        update_import_group_job_progress(group_job_id, processed, failed)

    try:
        for batch_start in range(0, len(valid_files), batch_size):
            batch = valid_files[batch_start : batch_start + batch_size]
            logger.info(
                f"[{group_name}] batch {batch_start // batch_size + 1} "
                f"({len(batch)} images, {batch_start + len(batch)}/{len(valid_files)})"
            )

            # Prepare images with bounded concurrency to control peak memory use.
            prepared_results = []
            for sub_start in range(0, len(batch), concurrency):
                sub_batch = batch[sub_start : sub_start + concurrency]
                futures = [
                    prepare_single_image.submit(
                        image_path=image_path,
                        metadata={
                            "author": author,
                            "group_name": group_name,
                            "name": file_info.get("name") or group_name,
                            "tags": file_info.get("tags", []),
                            "gridded": file_info.get("gridded"),
                            "grid_width": file_info.get("grid_width"),
                            "grid_height": file_info.get("grid_height"),
                            "subgroup": file_info.get("subgroup"),
                            "image_type": file_info.get("image_type", "battlemap"),
                            "content_hash": file_info.get("content_hash"),
                            "media_type": file_info.get("media_type"),
                            "reuse_storage_key": file_info.get("reuse_storage_key"),
                            "reuse_thumbnail_key": file_info.get("reuse_thumbnail_key"),
                        },
                    )
                    for file_info, image_path in sub_batch
                ]
                prepared_results.extend(f.result() for f in futures)

            # Batch CLIP → batch DB → batch Qdrant
            batch_results, _ = _process_batch(prepared_results)
            batch_success = sum(1 for r in batch_results if r["status"] == "success")
            processed += batch_success
            failed += len(batch_results) - batch_success
            update_import_group_job_progress(group_job_id, processed, failed)

        update_import_group_job_progress(group_job_id, processed, failed, status="completed")
        logger.info(f"Group {group_job_id} ({group_name}): {processed} ok, {failed} failed")
    except Exception as e:
        # Count all files not yet processed as failed, mark group as failed
        remaining = len(valid_files) - processed - failed
        failed += remaining
        logger.error(
            f"Group {group_job_id} ({group_name}) failed after {processed} images: {e}"
        )
        update_import_group_job_progress(group_job_id, processed, failed, status="failed")
        raise  # re-raise so process_import_job can catch it per-group

    return processed, failed


def _mark_group_job_failed(group_job_id: str, error_message: str) -> None:
    """Mark an ImportGroupJob as failed with an error message.

    Non-fatal: any DB error is logged and swallowed so it never propagates
    to the caller (which is already handling a failure scenario).
    """
    logger = get_logger(__name__)
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
                logger.info(f"Marked group job {group_job_id} as failed")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not mark group job {group_job_id} as failed: {e}")


def _finalize_import_job(job_id: str) -> None:
    """Mark ImportJob as completed/failed once all its groups are terminal.

    Called at the end of every import flow so the parent job status is
    written back to the DB — the tray and /active endpoint both read this.
    """
    logger = get_logger(__name__)
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not job:
            return
        groups = db.query(ImportGroupJob).filter(ImportGroupJob.job_id == job_id).all()
        if not groups:
            return
        terminal = {"completed", "failed", "cancelled"}
        if all(g.status in terminal for g in groups):
            job.status = "failed" if any(g.status == "failed" for g in groups) else "completed"
            job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
            logger.info(f"Import job {job_id} finalized as '{job.status}'")
    finally:
        db.close()


def _rebuild_fts() -> None:
    """Rebuild the FTS index (non-fatal on error)."""
    logger = get_logger(__name__)
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
        logger.warning(f"FTS rebuild failed (non-fatal): {e}")


@flow(name="process_import_group", log_prints=True)
def process_import_group(
    job_id: str,
    group_job_id: str,
    staging_dir: str,
    author: str,
    group_name: str,
    files: list[dict],
) -> dict:
    """Process a single confirmed group (single-group import path).

    For multi-group imports prefer process_import_job, which handles all groups
    in one Python process so the CLIP model is loaded only once.
    """
    logger = get_logger(__name__)
    logger.info(
        f"Processing import group '{group_name}' by '{author}' "
        f"({len(files)} files) for job {job_id}, group {group_job_id}"
    )
    processed, failed = _run_group(group_job_id, staging_dir, author, group_name, files)
    _finalize_import_job(job_id)
    if processed > 0:
        _rebuild_fts()
    return {
        "job_id": job_id,
        "group_job_id": group_job_id,
        "processed": processed,
        "failed": failed,
        "total": len(files),
    }


@flow(name="process_import_job", log_prints=True)
def process_import_job(
    job_id: str,
    staging_dir: str,
    groups: list[dict],
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
    logger = get_logger(__name__)
    logger.info(f"Starting import job {job_id}: {len(groups)} group(s) in {staging_dir}")
    total_processed = 0
    total_failed = 0

    try:
        for group in groups:
            group_job_id = group["group_job_id"]
            author = group["author"]
            group_name = group["group_name"]
            files = group["files"]
            logger.info(f"Processing group '{group_name}' by '{author}' ({len(files)} files)")
            try:
                processed, failed = _run_group(
                    group_job_id, staging_dir, author, group_name, files
                )
                total_processed += processed
                total_failed += failed
            except Exception as e:
                # _run_group already updated the group job status to "failed".
                # We log the error, count all unprocessed files as failed, and
                # continue with the next group so the job doesn't abort early.
                logger.error(
                    f"Group '{group_name}' ({group_job_id}) raised an unhandled exception, "
                    f"skipping to next group: {e}"
                )
                total_failed += len(files)
    finally:
        # Always finalize the job, rebuild FTS, and clean up staging — even if
        # some groups raised unexpected exceptions.
        _finalize_import_job(job_id)
        if total_processed > 0:
            _rebuild_fts()
        staging_path = Path(staging_dir)
        if staging_path.exists():
            shutil.rmtree(staging_path, ignore_errors=True)
            logger.info(f"Cleaned up staging dir for job {job_id}")

    logger.info(f"Import job {job_id} complete: {total_processed} processed, {total_failed} failed")
    return {
        "job_id": job_id,
        "processed": total_processed,
        "failed": total_failed,
        "total_groups": len(groups),
    }

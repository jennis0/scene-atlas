"""Main image ingestion Prefect flows.

Flows:
    analyse_upload       — Parse and group uploaded files for the preview UI
    process_import_group — Process a confirmed variant group (batched pipeline)
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

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from prefect import flow, task
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import (
    Color,
    Image,
    ImportGroupJob,
    ImportJob,
    Tag,
    TagCategory,
    VariantGroup,
    get_engine,
    get_session_local,
)
from backend.app.services import BattlemapParser, get_image_store, qdrant_service
from backend.app.services.fts_service import fts_rebuild

from .tasks.embedding_generation import (
    batch_generate_clip_embeddings,
    generate_clip_embedding,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: Build parser with tag vocabulary
# ---------------------------------------------------------------------------


def _build_parser() -> BattlemapParser:
    """Create a BattlemapParser with tag vocabulary loaded from DB."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        categories = db.query(TagCategory).all()
        cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
        return BattlemapParser(tag_categories=cat_dicts)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helper: Save one image dict to DB (shared logic for single and batch)
# ---------------------------------------------------------------------------


def _save_image_to_db(db: Session, image_data: dict) -> int:
    """Save one image and its tags/colors to the database within an existing session.

    Returns the image ID. Does NOT commit — caller must commit.
    """
    existing = db.query(Image).filter(Image.storage_key == image_data["storage_key"]).first()

    if existing:
        logger.info(f"Image already exists: {image_data['storage_key']}, updating...")
        image = existing
        image.name = image_data["name"]
        image.author = image_data.get("author")
        image.gridded = image_data.get("gridded")
        image.grid_width = image_data.get("grid_width")
        image.grid_height = image_data.get("grid_height")
        image.sub_variant = image_data.get("sub_variant")
    else:
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
            sub_variant=image_data.get("sub_variant"),
        )
        db.add(image)
        db.flush()

    # Handle variant group
    variant_group_name = image_data.get("variant_group_name")
    author = image_data.get("author")
    if variant_group_name:
        vg = (
            db.query(VariantGroup)
            .filter(
                VariantGroup.base_name == variant_group_name,
                VariantGroup.author == author,
            )
            .first()
        )
        if not vg:
            vg = VariantGroup(base_name=variant_group_name, author=author)
            db.add(vg)
            db.flush()
        image.variant_group_id = vg.id

    # Replace tags
    if existing:
        db.query(Tag).filter(Tag.image_id == image.id).delete()
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

    # Replace colors
    if existing:
        db.query(Color).filter(Color.image_id == image.id).delete()
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
def scan_directory(directory: str) -> List[str]:
    """Scan directory for supported image files."""
    directory_obj = Path(directory)
    logger.info(f"Scanning directory: {directory_obj}")
    image_paths = []

    for ext in settings.supported_formats:
        for path in directory_obj.rglob(f"*{ext}"):
            if "__MACOSX" in path.parts or path.name.startswith("._"):
                continue
            image_paths.append(str(path))

    logger.info(f"Found {len(image_paths)} images in {directory_obj}")
    return image_paths


@task(name="prepare_single_image", retries=2)
def prepare_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
    parser: BattlemapParser | None = None,
) -> dict:
    """Prepare a single image: parse metadata, copy to store, thumbnails, colors.

    This task handles everything EXCEPT CLIP embedding and database/Qdrant saves,
    which are batched separately for better throughput.

    Runs inline (not sub-tasks) for minimal overhead when submitted concurrently.

    Args:
        image_path: Absolute path to the image file
        source_dir: Root directory for relative path parsing (CLI mode)
        metadata: Explicit metadata dict (web import mode)
        parser: Pre-built BattlemapParser (avoids rebuilding per image in batch)

    Returns:
        Dict with 'status', 'image_data', 'original_image_path', 'qdrant_metadata'
    """
    image_path_obj = Path(image_path)
    logger.info(f"Preparing image: {image_path_obj.name}")

    try:
        # --- Parse metadata ---
        if metadata:
            author = metadata.get("author")
            variant_group_name = metadata.get("variant_group_name")
            name = metadata.get("name") or variant_group_name
            sub_variant = metadata.get("sub_variant")
            gridded = metadata.get("gridded")
            grid_width = metadata.get("grid_width")
            grid_height = metadata.get("grid_height")
            tags = metadata.get("tags", [])
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
            variant_group_name = parsed["variant_group_name"]
            name = variant_group_name
            sub_variant = parsed["sub_variant"]
            gridded = parsed["gridded"]
            grid_width = parsed["grid_width"]
            grid_height = parsed["grid_height"]
            tags = parsed["tags"]

        # --- Copy image into ImageStore ---
        image_store = get_image_store()
        storage_key_stem = uuid.uuid4().hex[:12]
        ext = image_path_obj.suffix.lower()
        storage_key = f"{storage_key_stem}{ext}"
        image_store.put(storage_key, image_path_obj)

        # --- File size (inline, fast) ---
        file_size = image_path_obj.stat().st_size

        # --- Generate thumbnails + get dimensions (inline call to the function) ---
        # Call the underlying function directly (not as Prefect task) to avoid overhead
        from backend.flows.tasks.image_processing import generate_thumbnails as _gen_thumbs

        thumbnail_result = _gen_thumbs.fn(image_path, storage_key_stem)
        thumbnail_keys = thumbnail_result["keys"]
        width, height = thumbnail_result["dimensions"]
        thumbnail_key = thumbnail_keys.get("medium", thumbnail_keys.get("small"))

        # --- Extract colors (inline call) ---
        from backend.flows.tasks.color_extraction import extract_dominant_colors as _extract_colors

        colors = _extract_colors.fn(image_path)

        # --- Build result ---
        image_data = {
            "filename": image_path_obj.name,
            "storage_key": storage_key,
            "name": name,
            "author": author,
            "variant_group_name": variant_group_name,
            "width": width,
            "height": height,
            "file_size": file_size,
            "thumbnail_key": thumbnail_key,
            "gridded": gridded,
            "grid_width": grid_width,
            "grid_height": grid_height,
            "sub_variant": sub_variant,
            "tags": tags,
            "colors": colors,
        }

        qdrant_metadata = {
            "filename": image_path_obj.name,
            "author": author,
            "base_name": variant_group_name,
        }

        return {
            "status": "success",
            "image_data": image_data,
            "original_image_path": image_path,
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
def save_to_qdrant(image_id: int, embedding: List[float], metadata: dict) -> bool:
    """Save embedding to Qdrant."""
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
def batch_save_to_database(image_data_list: List[dict]) -> List[int]:
    """Save multiple images to the database in a single transaction.

    Args:
        image_data_list: List of image data dicts

    Returns:
        List of image IDs
    """
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
def batch_save_to_qdrant(items: List[dict]) -> bool:
    """Save multiple embeddings to Qdrant in one call.

    Args:
        items: List of dicts with 'image_id', 'embedding', 'metadata'

    Returns:
        Success status
    """
    try:
        success = qdrant_service.batch_add_embeddings(items)
        if success:
            logger.info(f"Batch saved {len(items)} embeddings to Qdrant")
        return success
    except Exception as e:
        logger.error(f"Error batch saving to Qdrant: {e}")
        raise


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
                group_job.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Batch processing helper
# ---------------------------------------------------------------------------


def _process_batch(
    prepared_results: List[dict],
) -> tuple[List[dict], int]:
    """Process a batch of prepared images: CLIP embed, DB save, Qdrant save.

    Args:
        prepared_results: List of results from prepare_single_image

    Returns:
        Tuple of (all_results including failures, count of batch failures)
    """
    # Separate successes from failures
    successful = [r for r in prepared_results if r["status"] == "success"]
    batch_failed = len(prepared_results) - len(successful)

    if not successful:
        return prepared_results, batch_failed

    # Batch CLIP embedding
    image_paths = [r["original_image_path"] for r in successful]
    embeddings = batch_generate_clip_embeddings(image_paths)

    # Attach embeddings to image data
    for prep, embedding in zip(successful, embeddings):
        prep["embedding"] = embedding

    # Batch DB save
    image_data_list = [r["image_data"] for r in successful]
    image_ids = batch_save_to_database(image_data_list)

    # Batch Qdrant save
    qdrant_items = [
        {
            "image_id": image_id,
            "embedding": prep["embedding"],
            "metadata": prep["qdrant_metadata"],
        }
        for image_id, prep in zip(image_ids, successful)
    ]
    batch_save_to_qdrant(qdrant_items)

    # Attach image IDs to results
    for prep, image_id in zip(successful, image_ids):
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
def bulk_image_ingestion(source_dirs: List[str]) -> dict:
    """Ingest images from multiple directories using batched pipeline.

    Images are processed in batches for maximum throughput:
    - prepare_single_image tasks run concurrently via .submit()
    - CLIP embeddings are generated in batch (vectorized forward pass)
    - Database and Qdrant saves are batched into single transactions
    """
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
) -> list[dict]:
    """Parse and group uploaded files for the preview UI.

    Preview images are served directly from staging via the /preview/ endpoint
    (or from browser blob URLs when files were uploaded individually).
    No server-side thumbnail generation is done here — the frontend handles previews.
    """
    logger.info(f"Analysing {len(relative_paths)} uploaded files in {staging_dir}")

    parser = _build_parser()
    groups = parser.group_files(relative_paths)

    logger.info(f"Detected {len(groups)} variant group(s)")
    for g in groups:
        logger.info(
            f"  {g.get('author', '?')} / {g['variant_group_name']} ({len(g['files'])} files)"
        )

    return groups


# ---------------------------------------------------------------------------
# Shared group-processing helper (used by both single-group and job flows)
# ---------------------------------------------------------------------------


def _run_group(
    group_job_id: str,
    staging_dir: str,
    author: str,
    variant_group_name: str,
    files: list[dict],
) -> tuple[int, int]:
    """Process one variant group end-to-end and return (processed, failed) counts.

    Updates ImportGroupJob progress after every batch and marks it completed
    when done.  Intended to be called from a Prefect flow context.
    """
    batch_size = settings.ingestion_batch_size
    concurrency = settings.max_concurrent_prepare
    staging = Path(staging_dir)
    processed = 0
    failed = 0

    # Filter to files that actually exist in staging
    valid_files = []
    for file_info in files:
        image_path = staging / file_info["relative_path"]
        if not image_path.exists():
            logger.warning(f"File not found in staging: {image_path}")
            failed += 1
        else:
            valid_files.append((file_info, str(image_path)))

    if failed > 0:
        update_import_group_job_progress(group_job_id, processed, failed)

    for batch_start in range(0, len(valid_files), batch_size):
        batch = valid_files[batch_start : batch_start + batch_size]
        logger.info(
            f"[{variant_group_name}] batch {batch_start // batch_size + 1} "
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
                        "variant_group_name": variant_group_name,
                        "name": file_info.get("name") or variant_group_name,
                        "tags": file_info.get("tags", []),
                        "gridded": file_info.get("gridded"),
                        "grid_width": file_info.get("grid_width"),
                        "grid_height": file_info.get("grid_height"),
                        "sub_variant": file_info.get("sub_variant"),
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
    logger.info(f"Group {group_job_id} ({variant_group_name}): {processed} ok, {failed} failed")
    return processed, failed


def _rebuild_fts() -> None:
    """Rebuild the FTS index (non-fatal on error)."""
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
    variant_group_name: str,
    files: list[dict],
) -> dict:
    """Process a single confirmed variant group (single-group import path).

    For multi-group imports prefer process_import_job, which handles all groups
    in one Python process so the CLIP model is loaded only once.
    """
    logger.info(
        f"Processing import group '{variant_group_name}' by '{author}' "
        f"({len(files)} files) for job {job_id}, group {group_job_id}"
    )
    processed, failed = _run_group(group_job_id, staging_dir, author, variant_group_name, files)
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
    """Process all variant groups for an import job in a single flow run.

    Running all groups here — rather than one flow per group — means the CLIP
    model (~600 MB) is loaded exactly once for the whole job instead of once
    per group in separate subprocesses.  Groups are processed sequentially so
    peak memory stays bounded regardless of how many groups are in the job.

    Each group dict must contain:
        group_job_id, author, variant_group_name, files (list[dict])
    """
    logger.info(f"Starting import job {job_id}: {len(groups)} group(s) in {staging_dir}")
    total_processed = 0
    total_failed = 0

    for group in groups:
        group_job_id = group["group_job_id"]
        author = group["author"]
        variant_group_name = group["variant_group_name"]
        files = group["files"]
        logger.info(f"Processing group '{variant_group_name}' by '{author}' ({len(files)} files)")
        processed, failed = _run_group(group_job_id, staging_dir, author, variant_group_name, files)
        total_processed += processed
        total_failed += failed

    if total_processed > 0:
        _rebuild_fts()

    logger.info(f"Import job {job_id} complete: {total_processed} processed, {total_failed} failed")
    return {
        "job_id": job_id,
        "processed": total_processed,
        "failed": total_failed,
        "total_groups": len(groups),
    }

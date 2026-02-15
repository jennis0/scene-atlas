"""Main image ingestion Prefect flows.

Flows:
    analyse_upload       — Parse and group uploaded files for the preview UI
    process_import_group — Process a confirmed variant group end-to-end
    process_single_image — Process one image (subflow, used by the above + CLI)
    bulk_image_ingestion — CLI batch ingestion from directories
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
    ImportJob,
    Tag,
    TagCategory,
    VariantGroup,
    get_engine,
    get_session_local,
)
from backend.app.services import BattlemapParser, get_image_store, qdrant_service

from .tasks.color_extraction import extract_dominant_colors
from .tasks.embedding_generation import generate_clip_embedding
from .tasks.image_processing import (
    generate_preview_thumbnail,
    generate_thumbnails,
    get_file_size,
    get_image_dimensions,
)

logger = logging.getLogger(__name__)


@task(name="scan_directory", retries=1)
def scan_directory(directory: str) -> List[str]:
    """Scan directory for supported image files.

    Args:
        directory: Directory to scan (as string for serialization)

    Returns:
        List of image file paths as strings
    """
    directory_obj = Path(directory)
    logger.info(f"Scanning directory: {directory_obj}")
    image_paths = []

    for ext in settings.supported_formats:
        for path in directory_obj.rglob(f"*{ext}"):
            # Skip macOS resource forks and metadata
            if "__MACOSX" in path.parts or path.name.startswith("._"):
                continue
            image_paths.append(str(path))

    logger.info(f"Found {len(image_paths)} images in {directory_obj}")
    return image_paths


@task(name="save_to_database", retries=2)
def save_to_database(image_data: dict) -> int:
    """Save image and related data to SQLite database.

    Args:
        image_data: Dict containing all image information

    Returns:
        Image ID
    """
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    try:
        # Check if image already exists (by storage_key)
        existing = db.query(Image).filter(
            Image.storage_key == image_data["storage_key"]
        ).first()

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
            vg = db.query(VariantGroup).filter(
                VariantGroup.base_name == variant_group_name,
                VariantGroup.author == author,
            ).first()
            if not vg:
                vg = VariantGroup(base_name=variant_group_name, author=author)
                db.add(vg)
                db.flush()
            image.variant_group_id = vg.id

        # Replace tags
        if existing:
            db.query(Tag).filter(Tag.image_id == image.id).delete()

        for tag_data in image_data.get("tags", []):
            tag = Tag(
                image_id=image.id,
                category=tag_data["category"],
                value=tag_data["value"],
                confidence=tag_data.get("confidence", 1.0),
                source=tag_data.get("source", "auto"),
            )
            db.add(tag)

        # Replace colors
        if existing:
            db.query(Color).filter(Color.image_id == image.id).delete()

        for color_data in image_data.get("colors", []):
            color = Color(
                image_id=image.id,
                color_hex=color_data["color_hex"],
                percentage=color_data["percentage"],
                color_order=color_data["color_order"],
            )
            db.add(color)

        db.commit()
        image_id = image.id
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
    """Save embedding to Qdrant.

    Args:
        image_id: Image ID (from SQLite)
        embedding: CLIP embedding vector
        metadata: Metadata to store with the embedding

    Returns:
        Success status
    """
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


def _build_parser() -> BattlemapParser:
    """Create a BattlemapParser with tag vocabulary loaded from DB."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        categories = db.query(TagCategory).all()
        cat_dicts = [
            {"name": c.name, "common_values": c.common_values}
            for c in categories
        ]
        return BattlemapParser(tag_categories=cat_dicts)
    finally:
        db.close()


@flow(name="process_single_image", log_prints=True)
def process_single_image(
    image_path: str,
    source_dir: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Process a single image: extract metadata, generate thumbnails, embeddings, etc.

    Args:
        image_path: Absolute path to the image file (as string for serialization)
        source_dir: Root directory the image was scanned from (for relative path parsing)
        metadata: Optional explicit metadata dict (from web import).
                  If provided, uses these values instead of parsing from path.

    Returns:
        Dict with processing results
    """
    image_path_obj = Path(image_path)
    logger.info(f"Processing image: {image_path_obj}")

    try:
        # --- Parse metadata ---
        if metadata:
            # Web import: use explicit metadata (author + group from user, rest from parser)
            author = metadata.get("author")
            variant_group_name = metadata.get("variant_group_name")
            sub_variant = metadata.get("sub_variant")
            gridded = metadata.get("gridded")
            grid_width = metadata.get("grid_width")
            grid_height = metadata.get("grid_height")
            tags = metadata.get("tags", [])
        else:
            # CLI import: parse from path
            parser = _build_parser()
            source_dir_obj = Path(source_dir) if source_dir else None
            if source_dir_obj:
                relative = image_path_obj.relative_to(source_dir_obj)
            else:
                relative = Path(image_path_obj.name)
            parsed = parser.parse(str(relative))
            author = parsed["author"]
            variant_group_name = parsed["variant_group_name"]
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

        # --- Get image properties ---
        width, height = get_image_dimensions(image_path)
        file_size = get_file_size(image_path)

        # --- Generate thumbnails ---
        thumbnail_keys = generate_thumbnails(image_path, storage_key_stem)
        thumbnail_key = thumbnail_keys.get("medium", thumbnail_keys.get("small"))

        # --- Extract colors ---
        colors = extract_dominant_colors(image_path)

        # --- Generate CLIP embedding ---
        embedding = generate_clip_embedding(image_path)

        # --- Prepare image data ---
        image_data = {
            "filename": image_path_obj.name,
            "storage_key": storage_key,
            "name": variant_group_name,
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

        # --- Save to database ---
        image_id = save_to_database(image_data)

        # --- Save embedding to Qdrant ---
        save_to_qdrant(
            image_id=image_id,
            embedding=embedding,
            metadata={
                "filename": image_path_obj.name,
                "author": author,
                "base_name": variant_group_name,
            }
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
    """Ingest images from multiple directories.

    Args:
        source_dirs: List of directory paths to scan

    Returns:
        Summary of ingestion results
    """
    logger.info(f"Starting bulk ingestion from {len(source_dirs)} directories")

    all_results = []
    total_images = 0

    for dir_path in source_dirs:
        directory = Path(dir_path)
        if not directory.exists():
            logger.warning(f"Directory does not exist: {directory}")
            continue

        # Scan directory for images
        image_paths = scan_directory(dir_path)
        total_images += len(image_paths)

        # Process each image
        for image_path in image_paths:
            result = process_single_image(image_path, source_dir=dir_path)
            all_results.append(result)

    # Summarize results
    successful = sum(1 for r in all_results if r["status"] == "success")
    failed = sum(1 for r in all_results if r["status"] == "failed")

    summary = {
        "total_images": total_images,
        "processed": len(all_results),
        "successful": successful,
        "failed": failed,
        "results": all_results,
    }

    logger.info(f"Bulk ingestion complete: {successful} successful, {failed} failed")

    return summary


@flow(name="analyse_upload", log_prints=True, persist_result=True)
def analyse_upload(
    staging_dir: str,
    relative_paths: list[str],
) -> list[dict]:
    """Parse and group uploaded files for the preview UI.

    Runs BattlemapParser.group_files() on the uploaded files and returns
    structured variant group data for the frontend to display.

    Args:
        staging_dir: Path to the staging directory (as string for serialization)
        relative_paths: List of relative file paths within staging_dir

    Returns:
        List of variant group dicts, each with:
        - author: str | None
        - variant_group_name: str
        - files: list of dicts with relative_path, parsed metadata
    """
    logger.info(f"Analysing {len(relative_paths)} uploaded files in {staging_dir}")

    parser = _build_parser()
    groups = parser.group_files(relative_paths)

    # Generate preview thumbnails for each file
    staging = Path(staging_dir)
    for group in groups:
        for f in group["files"]:
            rel_path = f["relative_path"]
            image_path = staging / rel_path
            if image_path.exists():
                thumb_name = generate_preview_thumbnail(
                    image_path=str(image_path),
                    staging_dir=staging_dir,
                    relative_path=rel_path,
                )
                f["preview_thumbnail"] = thumb_name

    logger.info(f"Detected {len(groups)} variant group(s)")
    for g in groups:
        logger.info(f"  {g.get('author', '?')} / {g['variant_group_name']} ({len(g['files'])} files)")

    return groups


@task(name="update_import_job_progress", retries=1)
def update_import_job_progress(
    job_id: str,
    processed: int,
    failed: int,
    status: str = "running",
) -> None:
    """Update ImportJob progress counters in the database."""
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if job:
            job.processed_files = processed
            job.failed_files = failed
            job.status = status
            if status == "completed":
                job.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@flow(name="process_import_group", log_prints=True)
def process_import_group(
    job_id: str,
    staging_dir: str,
    author: str,
    variant_group_name: str,
    files: list[dict],
) -> dict:
    """Process a confirmed variant group from web import.

    Uses the per-file metadata provided by the user (from the preview UI)
    directly, without re-parsing filenames.

    Args:
        job_id: ImportJob ID for progress tracking
        staging_dir: Path to the staging directory
        author: User-confirmed author name
        variant_group_name: User-confirmed variant group name
        files: List of dicts with relative_path and user-confirmed metadata
               (tags, gridded, grid_width, grid_height, sub_variant)

    Returns:
        Summary dict with processed/failed counts
    """
    logger.info(
        f"Processing import group '{variant_group_name}' by '{author}' "
        f"({len(files)} files) for job {job_id}"
    )

    staging = Path(staging_dir)

    processed = 0
    failed = 0

    for file_info in files:
        rel_path = file_info["relative_path"]
        image_path = staging / rel_path
        if not image_path.exists():
            logger.warning(f"File not found in staging: {image_path}")
            failed += 1
            update_import_job_progress(job_id, processed, failed)
            continue

        try:
            result = process_single_image(
                image_path=str(image_path),
                metadata={
                    "author": author,
                    "variant_group_name": variant_group_name,
                    "tags": file_info.get("tags", []),
                    "gridded": file_info.get("gridded"),
                    "grid_width": file_info.get("grid_width"),
                    "grid_height": file_info.get("grid_height"),
                    "sub_variant": file_info.get("sub_variant"),
                },
            )
            if result.get("status") == "success":
                processed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Failed to process {rel_path}: {e}")
            failed += 1

        # Update progress after each image
        update_import_job_progress(job_id, processed, failed)

    # Mark job as completed
    update_import_job_progress(job_id, processed, failed, status="completed")

    logger.info(f"Import job {job_id} complete: {processed} processed, {failed} failed")

    return {
        "job_id": job_id,
        "processed": processed,
        "failed": failed,
        "total": len(files),
    }

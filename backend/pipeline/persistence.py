"""Database and LanceDB persistence operations.

Handles saving prepared image data to SQLite and semantic search index.

Functions:
    batch_save_to_database         — Save multiple images in one transaction
    save_to_database               — Save single image to database
    batch_save_to_vector_db        — Save multiple embeddings to LanceDB
    save_to_vector_db              — Save single embedding to LanceDB
    update_import_group_job_progress  — Update job progress and error tracking
    _save_image_to_db              — Internal: save one image with tags/colors
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.models import Color, Image, ImageGroup, ImportGroupJob, Tag
from backend.app.services import get_lancedb_service
from backend.app.services.image_parser import build_search_text

from .db import pipeline_db


def _save_image_to_db(db: Session, image_data: dict, group: ImageGroup | None = None) -> int:
    """Save one image and its tags/colors to the database within an existing session.

    Always creates a new record (never updates an existing one by storage_key,
    since multiple records can now share the same storage_key for dedup).

    If `group` is provided it is used directly, skipping the ImageGroup SELECT.
    Pass a pre-resolved group from batch_save_to_database to avoid N+1 queries.

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

    # Handle group — use pre-resolved group if caller provided one (avoids N+1)
    group_name = image_data.get("group_name")
    author = image_data.get("author")
    if group_name:
        grp = group
        if grp is None:
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


def save_to_database(image_data: dict) -> int:
    """Save image and related data to SQLite database.

    Returns:
        Image ID
    """
    logger = logging.getLogger(__name__)
    try:
        with pipeline_db() as db:
            image_id = _save_image_to_db(db, image_data)
        logger.info("Saved image to database: %s (ID: %s)", image_data["filename"], image_id)
        return image_id
    except Exception as e:
        logger.error("Error saving to database: %s", e)
        raise


def save_to_vector_db(image_id: int, embedding: list[float], metadata: dict) -> bool:
    """Save embedding to LanceDB."""
    logger = logging.getLogger(__name__)
    try:
        success = get_lancedb_service().add_image_embedding(
            image_id=image_id,
            embedding=embedding,
            metadata=metadata,
        )
        if success:
            logger.info("Saved embedding to LanceDB for image_id=%s", image_id)
        return success
    except Exception as e:
        logger.error("Error saving to LanceDB: %s", e)
        raise


def batch_save_to_database(image_data_list: list[dict]) -> list[int]:
    """Save multiple images to the database in a single transaction.

    Args:
        image_data_list: List of image data dicts

    Returns:
        List of image IDs
    """
    logger = logging.getLogger(__name__)
    try:
        with pipeline_db() as db:
            image_ids = []
            # Resolve the group once for the whole batch (all images share the same group)
            resolved_group: ImageGroup | None = None
            if image_data_list:
                first = image_data_list[0]
                group_name = first.get("group_name")
                author = first.get("author")
                if group_name:
                    resolved_group = (
                        db.query(ImageGroup)
                        .filter(
                            ImageGroup.base_name == group_name,
                            ImageGroup.author == author,
                        )
                        .first()
                    )
            for image_data in image_data_list:
                image_id = _save_image_to_db(db, image_data, group=resolved_group)
                # If the group was just created by the first image, cache it for the rest
                if resolved_group is None and image_id:
                    saved = db.query(Image).filter(Image.id == image_id).first()
                    if saved and saved.group_id:
                        resolved_group = (
                            db.query(ImageGroup).filter(ImageGroup.id == saved.group_id).first()
                        )
                image_ids.append(image_id)
        logger.info("Batch saved %s images to database", len(image_ids))
        return image_ids
    except Exception as e:
        logger.error("Error batch saving to database: %s", e)
        raise


def batch_save_to_vector_db(items: list[dict]) -> bool:
    """Save multiple embeddings to LanceDB in one call.

    LanceDB is the semantic search index, not the source of truth.  A failure
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
        success = get_lancedb_service().batch_add_embeddings(items)
        if success:
            logger.info("Batch saved %s embeddings to LanceDB", len(items))
        return success
    except Exception as e:
        logger.warning(
            "LanceDB batch save failed (non-fatal — %s embeddings not indexed): %s", len(items), e
        )
        return False


def update_import_group_job_progress(
    group_job_id: str,
    processed: int,
    failed: int,
    status: str = "running",
    created_group_id: int | None = None,
    file_errors: list[dict] | None = None,
) -> None:
    """Update ImportGroupJob progress counters in the database."""
    with pipeline_db() as db:
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

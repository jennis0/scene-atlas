"""Main image ingestion Prefect flow."""

import logging
from pathlib import Path
from typing import List

from prefect import flow, task
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import (
    Color,
    Image,
    Tag,
    VariantGroup,
    get_engine,
    get_session_local,
)
from backend.app.services import qdrant_service

from .tasks.color_extraction import extract_dominant_colors
from .tasks.embedding_generation import generate_clip_embedding
from .tasks.image_processing import (
    generate_thumbnails,
    get_file_size,
    get_image_dimensions,
)
from .tasks.metadata_extraction import (
    extract_tags_from_filename,
    extract_tags_from_path,
    infer_author,
    infer_base_name,
    merge_tags,
)

logger = logging.getLogger(__name__)


@task(name="scan_directory", retries=1)
def scan_directory(directory: Path) -> List[Path]:
    """Scan directory for supported image files.

    Args:
        directory: Directory to scan

    Returns:
        List of image file paths
    """
    logger.info(f"Scanning directory: {directory}")
    image_paths = []

    for ext in settings.supported_formats:
        image_paths.extend(directory.rglob(f"*{ext}"))

    logger.info(f"Found {len(image_paths)} images in {directory}")
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
        # Check if image already exists
        existing = db.query(Image).filter(Image.filepath == str(image_data["filepath"])).first()

        if existing:
            logger.info(f"Image already exists: {image_data['filepath']}, updating...")
            image = existing
        else:
            # Create new image record
            image = Image(
                filename=image_data["filename"],
                filepath=str(image_data["filepath"]),
                name=image_data["name"],
                author=image_data.get("author"),
                width=image_data["width"],
                height=image_data["height"],
                file_size=image_data["file_size"],
                thumbnail_path=str(image_data["thumbnail_path"]),
            )
            db.add(image)
            db.flush()  # Get the image ID

        # Add tags
        # Delete existing tags if updating
        if existing:
            db.query(Tag).filter(Tag.image_id == image.id).delete()

        for tag_data in image_data["tags"]:
            tag = Tag(
                image_id=image.id,
                category=tag_data["category"],
                value=tag_data["value"],
                confidence=tag_data["confidence"],
                source=tag_data["source"],
            )
            db.add(tag)

        # Add colors
        # Delete existing colors if updating
        if existing:
            db.query(Color).filter(Color.image_id == image.id).delete()

        for color_data in image_data["colors"]:
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


@flow(name="process_single_image", log_prints=True)
def process_single_image(image_path: Path) -> dict:
    """Process a single image: extract metadata, generate thumbnails, embeddings, etc.

    Args:
        image_path: Path to the image file

    Returns:
        Dict with processing results
    """
    logger.info(f"Processing image: {image_path}")

    try:
        # Extract metadata from filename and path
        filename_tags = extract_tags_from_filename(image_path.name)
        path_tags = extract_tags_from_path(image_path)
        all_tags = merge_tags([filename_tags, path_tags])

        # Infer author and base name
        author = infer_author(image_path)

        # Use parent folder as base name if it looks like a map name
        # (more than 3 chars and not "images")
        parent_folder = image_path.parent.name
        if len(parent_folder) > 3 and parent_folder.lower() != "images" and parent_folder != author:
            base_name = parent_folder
        else:
            base_name = infer_base_name(image_path.name, all_tags)

        # Get image properties
        width, height = get_image_dimensions(image_path)
        file_size = get_file_size(image_path)

        # Generate thumbnails
        thumbnails = generate_thumbnails(image_path)
        thumbnail_path = thumbnails.get("medium", thumbnails.get("small"))

        # Extract colors
        colors = extract_dominant_colors(image_path)

        # Generate CLIP embedding
        embedding = generate_clip_embedding(image_path)

        # Prepare image data
        image_data = {
            "filename": image_path.name,
            "filepath": image_path,
            "name": base_name,
            "author": author,
            "width": width,
            "height": height,
            "file_size": file_size,
            "thumbnail_path": thumbnail_path,
            "tags": all_tags,
            "colors": colors,
        }

        # Save to database
        image_id = save_to_database(image_data)

        # Save embedding to Qdrant
        save_to_qdrant(
            image_id=image_id,
            embedding=embedding,
            metadata={
                "filename": image_path.name,
                "author": author,
                "base_name": base_name,
            }
        )

        logger.info(f"Successfully processed image: {image_path}")

        return {
            "status": "success",
            "image_id": image_id,
            "filepath": str(image_path),
        }

    except Exception as e:
        logger.error(f"Failed to process image {image_path}: {e}")
        return {
            "status": "failed",
            "filepath": str(image_path),
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
        image_paths = scan_directory(directory)
        total_images += len(image_paths)

        # Process each image (Prefect will handle parallelization based on config)
        for image_path in image_paths:
            result = process_single_image(image_path)
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


if __name__ == "__main__":
    """Run the ingestion flow from command line."""
    import sys

    # Default to data/images directory
    source_dirs = sys.argv[1:] if len(sys.argv) > 1 else ["data/images"]

    print(f"Starting ingestion from: {source_dirs}")
    result = bulk_image_ingestion(source_dirs)
    print(f"\nIngestion complete!")
    print(f"  Total: {result['total_images']}")
    print(f"  Successful: {result['successful']}")
    print(f"  Failed: {result['failed']}")

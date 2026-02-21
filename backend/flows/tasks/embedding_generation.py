"""Embedding generation tasks for Prefect flows."""

import logging
from pathlib import Path
from typing import List

from prefect import task

from backend.app.services import get_clip_service
from backend.app.config import settings

logger = logging.getLogger(__name__)


@task(name="generate_clip_embedding", retries=2, tags=["clip"])
def generate_clip_embedding(image_path: str) -> List[float]:
    """Generate CLIP embedding for a single image.

    Args:
        image_path: Path to the image (as string for serialization)

    Returns:
        CLIP embedding vector (512 dimensions)
    """
    try:
        clip_service = get_clip_service()
        embedding = clip_service.encode_image(Path(image_path))
        logger.debug(f"Generated CLIP embedding for {image_path}, size: {len(embedding)}")
        return embedding
    except Exception as e:
        logger.error(f"Error generating CLIP embedding for {image_path}: {e}")
        raise


@task(name="batch_generate_clip_embeddings", retries=2, tags=["clip"])
def batch_generate_clip_embeddings(
    image_paths: List[str],
    batch_size: int | None = None,
) -> List[List[float]]:
    """Generate CLIP embeddings for multiple images using batch inference.

    Processes images in sub-batches to manage memory while still benefiting
    from vectorized forward passes (3-5x faster than individual inference).

    Args:
        image_paths: List of image file paths
        batch_size: Images per forward pass (default from settings)

    Returns:
        List of embedding vectors, one per image
    """
    if batch_size is None:
        batch_size = settings.ingestion_batch_size

    try:
        clip_service = get_clip_service()
        all_embeddings: List[List[float]] = []

        for i in range(0, len(image_paths), batch_size):
            chunk = image_paths[i : i + batch_size]
            chunk_paths = [Path(p) for p in chunk]
            embeddings = clip_service.batch_encode_images(chunk_paths)
            all_embeddings.extend(embeddings)
            logger.debug(f"Batch CLIP: processed {i + len(chunk)}/{len(image_paths)} images")

        logger.info(f"Generated batch embeddings for {len(image_paths)} images")
        return all_embeddings

    except Exception as e:
        logger.error(f"Error batch generating CLIP embeddings: {e}")
        raise

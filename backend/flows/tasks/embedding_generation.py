"""Embedding generation tasks for Prefect flows."""

import logging
from pathlib import Path
from typing import List

from prefect import task

from backend.app.services import get_clip_service

logger = logging.getLogger(__name__)


@task(name="generate_clip_embedding", retries=2)
def generate_clip_embedding(image_path: str) -> List[float]:
    """Generate CLIP embedding for an image.

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

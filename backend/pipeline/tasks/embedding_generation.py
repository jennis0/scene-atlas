"""Embedding generation tasks."""

import logging
from pathlib import Path

from backend.app.services import get_clip_service


def batch_generate_clip_embeddings(
    image_paths: list[str],
    batch_size: int | None = None,
) -> list[list[float]]:
    """CLIP embeddings for *image_paths*, one per image, in input order.

    Processes images in sub-batches to bound memory while still benefiting
    from vectorised forward passes (3-5x faster than one at a time).
    """
    logger = logging.getLogger(__name__)
    clip_service = get_clip_service()

    if batch_size is None:
        from backend.pipeline.pipeline_config import PipelineConfig

        batch_size = PipelineConfig().ingestion_batch_size
    all_embeddings: list[list[float]] = []

    for i in range(0, len(image_paths), batch_size):
        chunk = image_paths[i : i + batch_size]
        chunk_paths = [Path(p) for p in chunk]
        embeddings = clip_service.batch_encode_images(chunk_paths)
        all_embeddings.extend(embeddings)
        logger.debug("Batch CLIP: processed %s/%s images", i + len(chunk), len(image_paths))

    logger.info("Generated batch embeddings for %s images", len(image_paths))
    return all_embeddings

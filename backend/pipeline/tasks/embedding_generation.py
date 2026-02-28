"""Embedding generation tasks."""

from pathlib import Path

from backend.app.services import get_clip_service
from backend.pipeline.logger import get_logger


def generate_clip_embedding(image_path: str) -> list[float]:
    """Generate CLIP embedding for a single image.

    Args:
        image_path: Path to the image (as string for serialization)

    Returns:
        CLIP embedding vector (512 dimensions)
    """
    logger = get_logger(__name__)
    try:
        clip_service = get_clip_service()
        embedding = clip_service.encode_image(Path(image_path))
        logger.debug("Generated CLIP embedding for %s, size: %s", image_path, len(embedding))
        return embedding
    except Exception as e:
        logger.error("Error generating CLIP embedding for %s: %s", image_path, e)
        raise


def batch_generate_clip_embeddings(
    image_paths: list[str],
    batch_size: int | None = None,
) -> list[list[float]]:
    """Generate CLIP embeddings for multiple images using batch inference.

    Processes images in sub-batches to manage memory while still benefiting
    from vectorized forward passes (3-5x faster than individual inference).

    Args:
        image_paths: List of image file paths
        batch_size: Images per forward pass (default from settings)

    Returns:
        List of embedding vectors, one per image
    """
    logger = get_logger(__name__)
    if batch_size is None:
        from backend.pipeline.pipeline_config import PipelineConfig

        batch_size = PipelineConfig().ingestion_batch_size

    try:
        clip_service = get_clip_service()
        all_embeddings: list[list[float]] = []

        for i in range(0, len(image_paths), batch_size):
            chunk = image_paths[i : i + batch_size]
            chunk_paths = [Path(p) for p in chunk]
            embeddings = clip_service.batch_encode_images(chunk_paths)
            all_embeddings.extend(embeddings)
            logger.debug("Batch CLIP: processed %s/%s images", i + len(chunk), len(image_paths))

        logger.info("Generated batch embeddings for %s images", len(image_paths))
        return all_embeddings

    except Exception as e:
        logger.error("Error batch generating CLIP embeddings: %s", e)
        raise

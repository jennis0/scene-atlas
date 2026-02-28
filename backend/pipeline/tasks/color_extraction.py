"""Color extraction tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
from sklearn.cluster import KMeans

from backend.pipeline.logger import get_logger

if TYPE_CHECKING:
    from backend.pipeline.pipeline_config import PipelineConfig


def rgb_to_hex(rgb: tuple) -> str:
    """Convert RGB tuple to hex color string.

    Args:
        rgb: Tuple of (r, g, b) values

    Returns:
        Hex color string like '#1a2b3c'
    """
    return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"


def extract_dominant_colors(
    image_path: str,
    num_colors: int | None = None,
    pipeline_config: PipelineConfig | None = None,
) -> list[dict]:
    """Extract dominant colors from an image using k-means clustering.

    Args:
        image_path: Path to the image (as string for serialization)
        num_colors: Number of dominant colors to extract.
            Defaults to pipeline_config.num_dominant_colors or 5.
        pipeline_config: Optional pipeline config for clustering params.

    Returns:
        List of dicts with color info: [{"hex": "#abc123", "percentage": 45.2, "order": 1}, ...]
    """
    logger = get_logger(__name__)

    if pipeline_config is not None:
        _num_colors = num_colors if num_colors is not None else pipeline_config.num_dominant_colors
        _clustering_samples = pipeline_config.color_clustering_samples
        _n_init = pipeline_config.color_kmeans_n_init
    else:
        # Fallback: use PipelineConfig dataclass defaults
        from backend.pipeline.pipeline_config import PipelineConfig

        _defaults = PipelineConfig()
        _num_colors = num_colors if num_colors is not None else _defaults.num_dominant_colors
        _clustering_samples = _defaults.color_clustering_samples
        _n_init = _defaults.color_kmeans_n_init

    try:
        # Read image
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Could not read image: {image_path}")

        # Downsample to max 512px before processing — color extraction doesn't
        # need full resolution, and this reduces a 4000x4000 image from ~50MB to ~0.8MB.
        h, w = image.shape[:2]
        max_dim = 512
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            image = cv2.resize(
                image,
                (max(1, int(w * scale)), max(1, int(h * scale))),
                interpolation=cv2.INTER_AREA,
            )

        # Convert BGR to RGB
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Reshape image to be a list of pixels
        pixels = image.reshape(-1, 3)

        # Sample pixels if image is large
        if len(pixels) > _clustering_samples:
            indices = np.random.choice(len(pixels), _clustering_samples, replace=False)
            pixels = pixels[indices]

        # Apply k-means clustering
        kmeans = KMeans(n_clusters=_num_colors, random_state=42, n_init=_n_init)
        kmeans.fit(pixels)

        # Get cluster centers (dominant colors)
        colors = kmeans.cluster_centers_

        # Get the percentage of each color
        labels = kmeans.labels_
        label_counts = np.bincount(labels)
        total_pixels = len(labels)
        percentages = (label_counts / total_pixels) * 100

        # Sort colors by percentage (descending)
        sorted_indices = np.argsort(percentages)[::-1]

        # Format results
        dominant_colors = []
        for order, idx in enumerate(sorted_indices, start=1):
            color = colors[idx]
            percentage = percentages[idx]
            hex_color = rgb_to_hex(color)

            dominant_colors.append(
                {
                    "color_hex": hex_color,
                    "percentage": float(percentage),
                    "color_order": order,
                }
            )

        logger.debug("Extracted %s colors from %s", len(dominant_colors), image_path)
        return dominant_colors

    except Exception as e:
        logger.error("Error extracting colors from %s: %s", image_path, e)
        raise

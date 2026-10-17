"""Color extraction tasks."""

from __future__ import annotations

import logging

import cv2
import numpy as np
from sklearn.cluster import KMeans

from backend.pipeline.pipeline_config import PipelineConfig


def rgb_to_hex(rgb: tuple) -> str:
    """``(r, g, b)`` → ``'#1a2b3c'``."""
    return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"


def extract_dominant_colors(
    image_path: str,
    num_colors: int | None = None,
    pipeline_config: PipelineConfig | None = None,
) -> list[dict]:
    """Dominant colors via k-means, most dominant first.

    Returns ``[{"color_hex": "#abc123", "percentage": 45.2, "color_order": 1}, ...]``.
    *num_colors* defaults to ``pipeline_config.num_dominant_colors`` (or 5).
    """
    logger = logging.getLogger(__name__)

    cfg = pipeline_config or PipelineConfig()
    _num_colors = num_colors if num_colors is not None else cfg.num_dominant_colors
    _clustering_samples = cfg.color_clustering_samples
    _n_init = cfg.color_kmeans_n_init

    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    if image.dtype == np.uint16:
        image = (image >> 8).astype(np.uint8)
    # Transparent pixels (RGBA WebP thumbnails) are excluded from clustering.
    alpha = None
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        alpha = image[:, :, 3]
        image = np.ascontiguousarray(image[:, :, :3])

    # Downsample to max 512px before processing — color extraction doesn't
    # need full resolution, and this reduces a 4000x4000 image from ~50MB to ~0.8MB.
    h, w = image.shape[:2]
    max_dim = 512
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
        if alpha is not None:
            alpha = cv2.resize(alpha, new_size, interpolation=cv2.INTER_AREA)

    # Convert BGR to RGB
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Reshape image to be a list of pixels
    pixels = image.reshape(-1, 3)
    if alpha is not None:
        visible = pixels[alpha.reshape(-1) >= 128]
        if len(visible) >= _num_colors:  # nearly all transparent: use every pixel
            pixels = visible

    # Sample pixels if image is large
    if len(pixels) > _clustering_samples:
        indices = np.random.choice(len(pixels), _clustering_samples, replace=False)
        pixels = pixels[indices]

    # Apply k-means clustering
    kmeans = KMeans(n_clusters=_num_colors, random_state=42, n_init=_n_init)  # pyright: ignore[reportArgumentType]
    labels = kmeans.fit_predict(pixels)

    # Get cluster centers (dominant colors)
    colors = kmeans.cluster_centers_

    # Get the percentage of each color
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

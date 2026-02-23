"""Color extraction tasks."""

import cv2
import numpy as np
from sklearn.cluster import KMeans

from backend.app.config import settings
from backend.flows.logger import get_logger


def rgb_to_hex(rgb: tuple) -> str:
    """Convert RGB tuple to hex color string.

    Args:
        rgb: Tuple of (r, g, b) values

    Returns:
        Hex color string like '#1a2b3c'
    """
    return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"


def extract_dominant_colors(image_path: str, num_colors: int = None) -> list[dict]:
    """Extract dominant colors from an image using k-means clustering.

    Args:
        image_path: Path to the image (as string for serialization)
        num_colors: Number of dominant colors to extract (default from settings)

    Returns:
        List of dicts with color info: [{"hex": "#abc123", "percentage": 45.2, "order": 1}, ...]
    """
    logger = get_logger(__name__)
    if num_colors is None:
        num_colors = settings.num_dominant_colors

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
        if len(pixels) > settings.color_clustering_samples:
            indices = np.random.choice(
                len(pixels), settings.color_clustering_samples, replace=False
            )
            pixels = pixels[indices]

        # Apply k-means clustering
        kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=settings.color_kmeans_n_init)
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

        logger.debug(f"Extracted {len(dominant_colors)} colors from {image_path}")
        return dominant_colors

    except Exception as e:
        logger.error(f"Error extracting colors from {image_path}: {e}")
        raise

"""Prefect flows package."""
 
from .ingestion import bulk_image_ingestion, process_single_image

__all__ = [
    "bulk_image_ingestion",
    "process_single_image",
]

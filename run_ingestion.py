#!/usr/bin/env python3
"""Run the image ingestion flow from a source directory.

Usage:
    uv run python run_ingestion.py /path/to/images
    uv run python run_ingestion.py /path/to/dir1 /path/to/dir2
"""

import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

# Set PREFECT_API_URL so flow runs are tracked by the Prefect server
os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

from backend.flows.ingestion import bulk_image_ingestion

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_ingestion.py <source_dir> [source_dir2 ...]")
        print()
        print("Scans the given directories for images and ingests them into the store.")
        print("Metadata (author, variant group, tags) is inferred from the directory structure.")
        print()
        print("Expected structure:")
        print("  source_dir/AuthorName/VariantGroup/image_variant.jpg")
        sys.exit(1)

    source_dirs = sys.argv[1:]

    # Validate paths exist
    for d in source_dirs:
        if not Path(d).exists():
            print(f"Error: directory does not exist: {d}")
            sys.exit(1)

    print("=" * 70)
    print("BATTLEMAP INGESTION FLOW")
    print("=" * 70)
    print(f"\nSource directories: {source_dirs}")
    print("\nProcessing images...")
    print("  - Extracting metadata from filenames")
    print("  - Generating thumbnails")
    print("  - Extracting dominant colors")
    print("  - Generating CLIP embeddings for semantic search")
    print()

    if "PREFECT_API_URL" not in str(sys.argv):
        print(
            "TIP: To view this in Prefect UI, run 'python start_prefect_ui.py' in another terminal"
        )
        print()

    # Run the flow
    result = bulk_image_ingestion(source_dirs)

    # Print summary
    print("\n" + "=" * 70)
    print("INGESTION COMPLETE")
    print("=" * 70)
    print(f"  Total images found: {result['total_images']}")
    print(f"  Successfully processed: {result['successful']}")
    print(f"  Failed: {result['failed']}")
    print()

    if result["failed"] > 0:
        print("Failed images:")
        for r in result["results"]:
            if r["status"] == "failed":
                print(f"  - {r.get('filename', 'unknown')}: {r.get('error', 'unknown error')}")
        print()

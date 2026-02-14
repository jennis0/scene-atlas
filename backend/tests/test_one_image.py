"""Test metadata extraction on a single image without full processing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.flows.tasks.metadata_extraction import (
    extract_tags_from_filename,
    extract_tags_from_path,
    infer_author,
    infer_base_name,
    merge_tags,
)

from backend.tests import FIXTURES_DIR

# Find first image
images_dir = FIXTURES_DIR
image_files = list(images_dir.glob("**/*.jpg")) + list(images_dir.glob("**/*.png"))

if not image_files:
    print("No images found!")
    sys.exit(1)

# Test on first few images
for img_path in image_files[:5]:
    print(f"\n{'='*60}")
    print(f"File: {img_path}")
    print(f"{'='*60}")

    # Extract metadata
    filename_tags = extract_tags_from_filename.fn(img_path.name)
    path_tags = extract_tags_from_path.fn(img_path)
    all_tags = merge_tags.fn([filename_tags, path_tags])

    author = infer_author.fn(img_path)
    base_name = infer_base_name.fn(img_path.name, all_tags)

    print(f"\nAuthor: {author}")
    print(f"Base Name: {base_name}")
    print(f"\nExtracted Tags ({len(all_tags)}):")
    for tag in all_tags:
        print(f"  - {tag['category']:12s}: {tag['value']:15s} (confidence: {tag['confidence']:.1f}, source: {tag['source']})")

print(f"\n{'='*60}")
print("Metadata extraction test complete!")

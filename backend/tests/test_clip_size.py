"""Test CLIP embedding size."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.app.services import get_clip_service

from backend.tests import FIXTURES_DIR

# Find a test image
images_dir = FIXTURES_DIR
image_files = list(images_dir.glob("**/*.jpg"))[:1]

if image_files:
    print(f"Testing with: {image_files[0].name}")

    clip_service = get_clip_service()
    embedding = clip_service.encode_image(image_files[0])

    print(f"Embedding size: {len(embedding)}")
    print(f"First 5 values: {embedding[:5]}")
else:
    print("No images found!")

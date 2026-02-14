"""Inspect CLIP model structure."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.app.services import get_clip_service

clip_service = get_clip_service()

print("CLIP Model Structure:")
print(f"Model: {clip_service.model.__class__.__name__}")
print(f"\nText model output:")
print(f"  - text_model.config.hidden_size: {clip_service.model.text_model.config.hidden_size}")
print(f"\nVision model output:")
print(f"  - vision_model.config.hidden_size: {clip_service.model.vision_model.config.hidden_size}")
print(f"\nProjection dimensions:")
print(f"  - projection_dim: {clip_service.model.config.projection_dim}")

# Test both encoding methods
text_emb = clip_service.encode_text("test")
print(f"\nActual dimensions:")
print(f"  - Text embedding: {len(text_emb)}")

from backend.tests import FIXTURES_DIR

# Find an image to test
images_dir = FIXTURES_DIR
image_files = list(images_dir.glob("**/*.jpg"))[:1]
if image_files:
    image_emb = clip_service.encode_image(image_files[0])
    print(f"  - Image embedding: {len(image_emb)}")

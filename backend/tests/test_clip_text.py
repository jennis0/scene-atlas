"""Test CLIP text encoding."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.app.services import get_clip_service

print("Testing CLIP text encoding...")
clip_service = get_clip_service()

# Test text encoding
text = "abandoned mine"
print(f"Encoding text: '{text}'")

try:
    embedding = clip_service.encode_text(text)
    print(f"[OK] Text encoding successful!")
    print(f"     Embedding size: {len(embedding)}")
    print(f"     First 5 values: {embedding[:5]}")
except Exception as e:
    print(f"[ERROR] Text encoding failed: {e}")
    import traceback
    traceback.print_exc()

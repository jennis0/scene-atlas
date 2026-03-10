"""Generate minimal test images for E2E tests.

Uses the same pattern as backend/tests/conftest.py make_test_image fixture.
Never commits binary blobs — these are generated fresh each run.
"""

import argparse
import json
from pathlib import Path

from PIL import Image

IMAGES = [
    # (relative_path, width, height, color)
    # Group 1: ForestClearing (3 variants)
    ("TestArtist/ForestClearing/ForestClearing_Night.jpg", 40, 40, (30, 30, 80)),
    ("TestArtist/ForestClearing/ForestClearing_Summer.jpg", 40, 40, (100, 200, 100)),
    ("TestArtist/ForestClearing/ForestClearing_Winter.jpg", 40, 40, (200, 220, 240)),
    # Group 2: CaveEntrance (2 variants)
    ("TestArtist/CaveEntrance/CaveEntrance_Lava.jpg", 40, 40, (200, 60, 30)),
    ("TestArtist/CaveEntrance/CaveEntrance_Flooded.jpg", 40, 40, (30, 80, 200)),
    # Ungrouped
    ("LooseFile_Tavern.jpg", 40, 40, (180, 140, 90)),
]


def generate(output_dir: str) -> list[str]:
    out = Path(output_dir)
    paths = []
    for rel_path, w, h, color in IMAGES:
        full = out / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (w, h), color)
        img.save(full, format="JPEG", quality=70)
        paths.append(rel_path)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate E2E test images")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--list", action="store_true", help="Print paths as JSON")
    args = parser.parse_args()

    paths = generate(args.output_dir)
    if args.list:
        print(json.dumps(paths))
    else:
        print(f"Generated {len(paths)} test images in {args.output_dir}")

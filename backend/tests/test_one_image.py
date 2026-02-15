"""Test metadata extraction on a single image using BattlemapParser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.app.config import settings
from backend.app.models import TagCategory, get_engine, get_session_local, init_db, seed_tag_categories
from backend.app.services import BattlemapParser
from backend.tests import FIXTURES_DIR

# Ensure DB is initialized with tag categories
engine = get_engine(settings.database_url)
init_db(engine)
SessionLocal = get_session_local(engine)
db = SessionLocal()
seed_tag_categories(db)

# Load parser with DB vocabulary
categories = db.query(TagCategory).all()
cat_dicts = [{"name": c.name, "common_values": c.common_values} for c in categories]
db.close()

parser = BattlemapParser(tag_categories=cat_dicts)

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

    # Parse metadata from relative path
    try:
        relative = img_path.relative_to(images_dir)
    except ValueError:
        relative = Path(img_path.name)

    parsed = parser.parse(str(relative))

    print(f"\nAuthor: {parsed['author']}")
    print(f"Variant Group: {parsed['variant_group_name']}")
    print(f"Sub-variant: {parsed['sub_variant']}")
    print(f"Gridded: {parsed['gridded']}")
    if parsed['grid_width']:
        print(f"Grid Dimensions: {parsed['grid_width']}x{parsed['grid_height']}")
    print(f"\nExtracted Tags ({len(parsed['tags'])}):")
    for tag in parsed['tags']:
        print(f"  - {tag['category']:12s}: {tag['value']:15s} (confidence: {tag['confidence']:.1f}, source: {tag['source']})")

print(f"\n{'='*60}")
print("Metadata extraction test complete!")

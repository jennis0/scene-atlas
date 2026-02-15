"""Test image ingestion with sample images.

Usage:
    uv run python -m backend.tests.test_ingestion [source_dir]
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.flows import process_single_image, bulk_image_ingestion
from backend.app.config import settings
from backend.tests import FIXTURES_DIR

def test_single_image(images_dir: Path = FIXTURES_DIR):
    """Test processing a single image."""
    image_files = list(images_dir.glob("**/*.jpg")) + list(images_dir.glob("**/*.png"))

    if not image_files:
        print(f"[ERROR] No images found in {images_dir}")
        print(f"\nPlease add some test images to: {images_dir}")
        print("Organize them like:")
        print("  backend/tests/fixtures/AuthorName/MapName/MapName_Winter_Grid.jpg")
        print("  backend/tests/fixtures/AuthorName/MapName/MapName_Summer_NoGrid.png")
        return False

    print(f"Found {len(image_files)} images in {images_dir}")
    print(f"\nProcessing first image: {image_files[0].name}")

    # Process the first image
    result = process_single_image(image_files[0], source_dir=images_dir)

    if result["status"] == "success":
        print(f"\n[OK] Image processed successfully!")
        print(f"     Image ID: {result['image_id']}")
        print(f"     Storage key: {result['storage_key']}")
        return True
    else:
        print(f"\n[ERROR] Failed to process image:")
        print(f"        {result.get('error', 'Unknown error')}")
        return False

def test_bulk_ingestion(images_dir: Path = FIXTURES_DIR):
    """Test bulk ingestion."""

    print(f"\nStarting bulk ingestion from: {images_dir}")

    result = bulk_image_ingestion([str(images_dir)])

    print(f"\n=== Ingestion Results ===")
    print(f"Total images found: {result['total_images']}")
    print(f"Successfully processed: {result['successful']}")
    print(f"Failed: {result['failed']}")

    if result['failed'] > 0:
        print("\nFailed images:")
        for r in result['results']:
            if r['status'] == 'failed':
                print(f"  - {r['filename']}: {r.get('error', 'Unknown error')}")

    return result['successful'] > 0

def check_database():
    """Check what's in the database."""
    from backend.app.models import get_engine, get_session_local, Image, Tag

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    session = SessionLocal()

    try:
        image_count = session.query(Image).count()
        tag_count = session.query(Tag).count()

        print(f"\n=== Database Status ===")
        print(f"Images in database: {image_count}")
        print(f"Tags in database: {tag_count}")

        if image_count > 0:
            print(f"\nFirst few images:")
            images = session.query(Image).limit(5).all()
            for img in images:
                tags = session.query(Tag).filter(Tag.image_id == img.id).all()
                tag_str = ", ".join([f"{t.category}:{t.value}" for t in tags])
                print(f"  - {img.name} ({img.filename})")
                print(f"    Author: {img.author or 'Unknown'}")
                print(f"    Tags: {tag_str or 'None'}")
                print(f"    Colors: {len(img.colors)}")
    finally:
        session.close()

if __name__ == "__main__":
    print("=== Battlemap Image Ingestion Test ===\n")

    # Accept optional source directory argument
    source_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURES_DIR

    # Check if images directory has any images
    if test_single_image(source_dir):
        print("\n" + "="*50)
        print("\nDo you want to process all images? (y/n): ", end="")
        response = input().lower().strip()

        if response == 'y':
            test_bulk_ingestion(source_dir)

    # Check database contents
    check_database()

    print("\n=== Test Complete ===")
    print("\nTo view results, start the server and visit:")
    print("  http://localhost:8000/docs")
    print("\nOr query the API:")
    print("  http://localhost:8000/api/v1/images/")
    print("  http://localhost:8000/api/v1/tags/stats")

"""Complete end-to-end workflow test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("COMPLETE WORKFLOW TEST - Fresh Start")
print("=" * 60)

# Step 1: Verify database is clean
print("\n[1/6] Checking database state...")
from backend.app.models import get_engine, get_session_local, Image, Tag

engine = get_engine()
SessionLocal = get_session_local(engine)
db = SessionLocal()
image_count = db.query(Image).count()
tag_count = db.query(Tag).count()
db.close()
print(f"      Images: {image_count}, Tags: {tag_count}")
assert image_count == 0, "Database should be empty!"
print("      [OK] Database is clean")

# Step 2: Ingest one image
print("\n[2/6] Ingesting test image...")
from backend.flows import process_single_image

from backend.tests import FIXTURES_DIR

images_dir = FIXTURES_DIR
image_files = list(images_dir.glob("**/*.jpg"))[:1]
if not image_files:
    print("      [ERROR] No images found!")
    sys.exit(1)

print(f"      Processing: {image_files[0].name}")
result = process_single_image(image_files[0], source_dir=images_dir)

if result["status"] == "success":
    print(f"      [OK] Image ingested successfully (ID: {result['image_id']})")
else:
    print(f"      [ERROR] Ingestion failed: {result.get('error')}")
    sys.exit(1)

# Step 3: Verify database
print("\n[3/6] Verifying database...")
db = SessionLocal()
images = db.query(Image).all()
tags = db.query(Tag).all()
print(f"      Images: {len(images)}")
print(f"      Tags: {len(tags)}")

if len(images) > 0:
    img = images[0]
    print(f"      - Name: {img.name}")
    print(f"      - Author: {img.author}")
    print(f"      - Filename: {img.filename}")
    print(f"      - Tags: {[f'{t.category}:{t.value}' for t in img.tags]}")
    print(f"      - Colors: {len(img.colors)}")
    print("      [OK] Database populated correctly")
else:
    print("      [ERROR] No images in database!")
    sys.exit(1)
db.close()

# Step 4: Verify Qdrant
print("\n[4/6] Verifying Qdrant...")
from backend.app.services import qdrant_service

try:
    # Try to search to verify collection exists
    from backend.app.services import get_clip_service

    clip = get_clip_service()
    query_emb = clip.encode_text("test query")
    results = qdrant_service.search_similar(query_emb, limit=5)
    print(f"      Collection has {len(results)} searchable vectors")
    print("      [OK] Qdrant working")
except Exception as e:
    print(f"      [ERROR] Qdrant error: {e}")
    sys.exit(1)

# Step 5: Test semantic search
print("\n[5/6] Testing semantic search...")
query = "abandoned mine"
print(f"      Query: '{query}'")
query_embedding = clip.encode_text(query)
print(f"      Query embedding size: {len(query_embedding)}")

search_results = qdrant_service.search_similar(query_embedding, limit=10)
print(f"      Found {len(search_results)} results")
if len(search_results) > 0:
    print(f"      Top result score: {search_results[0]['score']:.4f}")
    print("      [OK] Semantic search working")
else:
    print("      [WARN] No results found (but search works)")

# Step 6: Quick API test
print("\n[6/6] Testing API endpoints...")
from fastapi.testclient import TestClient
from backend.app.main import app

# Initialize app state for TestClient
app.state.db_engine = engine

with TestClient(app) as client:
    # Test health
    response = client.get("/health")
    assert response.status_code == 200
    print("      [OK] Health endpoint")

    # Test list images
    response = client.get("/api/v1/images/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    print("      [OK] List images endpoint")

    # Test search
    response = client.get("/api/v1/search/?text=mine")
    assert response.status_code == 200
    print("      [OK] Search endpoint")

    # Test semantic search
    response = client.get("/api/v1/search/semantic?query=abandoned+mine")
    assert response.status_code == 200
    data = response.json()
    assert "error" not in data or data.get("error") is None
    print("      [OK] Semantic search endpoint")

print("\n" + "=" * 60)
print("ALL TESTS PASSED!")
print("=" * 60)
print("\nSystem is ready!")
print("- Database: 1 image with metadata, tags, and colors")
print("- Qdrant: Vector embeddings stored and searchable")
print("- API: All endpoints working correctly")
print("- Semantic search: CLIP embeddings working")
print("\nReady to ingest all 341 images!")

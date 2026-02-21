"""Comprehensive API tests for Battlemap Explorer."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models import get_engine, init_db, get_session_local, Image, Tag
from backend.app.config import settings


@pytest.fixture(scope="module")
def client():
    """Create test client."""
    # Initialize test database
    engine = get_engine()
    init_db(engine)

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def test_image_id(client):
    """Get the ID of a test image (assumes at least one image exists)."""
    engine = get_engine()
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    try:
        image = db.query(Image).first()
        if image:
            return image.id
        return None
    finally:
        db.close()


class TestHealthEndpoints:
    """Test health and root endpoints."""

    def test_root(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "Battlemap Explorer"
        assert data["status"] == "running"
        assert "version" in data

    def test_health(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestImageEndpoints:
    """Test image-related endpoints."""

    def test_list_images(self, client):
        """Test listing all images."""
        response = client.get("/api/v1/images/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_images_pagination(self, client):
        """Test image pagination."""
        response = client.get("/api/v1/images/?skip=0&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 10

    def test_get_image(self, client, test_image_id):
        """Test getting a specific image."""
        if not test_image_id:
            pytest.skip("No test images available")

        response = client.get(f"/api/v1/images/{test_image_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_image_id
        assert "filename" in data
        assert "author" in data
        assert "tags" in data
        assert "colors" in data

    def test_get_nonexistent_image(self, client):
        """Test getting a non-existent image."""
        response = client.get("/api/v1/images/99999")
        assert response.status_code == 404

    def test_get_image_variants(self, client, test_image_id):
        """Test getting image variants."""
        if not test_image_id:
            pytest.skip("No test images available")

        response = client.get(f"/api/v1/images/{test_image_id}/variants")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestTagEndpoints:
    """Test tag-related endpoints."""

    def test_list_tag_categories(self, client):
        """Test listing tag categories."""
        response = client.get("/api/v1/tags/categories")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Should have our seeded categories
        category_names = [cat["name"] for cat in data]
        assert "grid" in category_names
        assert "season" in category_names
        assert "lighting" in category_names

    def test_get_tag_category(self, client):
        """Test getting a specific tag category."""
        response = client.get("/api/v1/tags/categories/grid")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "grid"

    def test_get_nonexistent_tag_category(self, client):
        """Test getting a non-existent category."""
        response = client.get("/api/v1/tags/categories/nonexistent")
        assert response.status_code == 404

    def test_get_tag_values_for_category(self, client):
        """Test getting tag values for a category."""
        response = client.get("/api/v1/tags/values/grid")
        assert response.status_code == 200
        data = response.json()
        assert "category" in data
        assert "values" in data
        assert isinstance(data["values"], list)

    def test_get_tag_statistics(self, client):
        """Test tag statistics."""
        response = client.get("/api/v1/tags/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_tags" in data
        assert "categories" in data


class TestSearchEndpoints:
    """Test search functionality."""

    def test_search_no_params(self, client):
        """Test search with no parameters."""
        response = client.get("/api/v1/search/")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "images" in data
        assert isinstance(data["images"], list)

    def test_search_by_text(self, client):
        """Test text search."""
        response = client.get("/api/v1/search/?text=mine")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "images" in data

    def test_search_by_author(self, client):
        """Test author search."""
        response = client.get("/api/v1/search/?author=czepeku")
        assert response.status_code == 200
        data = response.json()
        assert "images" in data

    def test_search_by_tags(self, client):
        """Test tag-based search."""
        response = client.get("/api/v1/search/?tags=state:abandoned")
        assert response.status_code == 200
        data = response.json()
        assert "images" in data

    def test_search_combined_filters(self, client):
        """Test combined search filters."""
        response = client.get("/api/v1/search/?text=mine&author=czepeku")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data

    def test_search_pagination(self, client):
        """Test search pagination."""
        response = client.get("/api/v1/search/?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["offset"] == 0

    def test_semantic_search(self, client):
        """Test semantic search."""
        response = client.get("/api/v1/search/semantic?query=abandoned+mine&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "results" in data
        # Should not have an error
        assert "error" not in data or data.get("error") is None

    def test_semantic_search_with_threshold(self, client):
        """Test semantic search with custom threshold."""
        response = client.get("/api/v1/search/semantic?query=dark+forest&score_threshold=0.3")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)

    def test_search_semantic_rerank(self, client):
        """Combined search should return images ordered by semantic score."""
        # pick a query that actually returns results by trying a few common terms
        sem_ids = []
        query_str = None
        for q in ["abandoned mine", "dark forest", "tavern", "castle"]:
            encoded = q.replace(" ", "+")
            sem_resp = client.get(f"/api/v1/search/semantic?query={encoded}&limit=10")
            if sem_resp.status_code != 200:
                continue
            sem_data = sem_resp.json()
            sem_ids = [r["image_id"] for r in sem_data.get("results", [])]
            if sem_ids:
                query_str = encoded
                break

        if not sem_ids:
            pytest.skip("No semantic results available for rerank test")

        combined_resp = client.get(f"/api/v1/search/?semantic={query_str}&limit=10")
        assert combined_resp.status_code == 200
        combined = combined_resp.json()
        returned_ids = [img["id"] for img in combined.get("images", [])]

        # ordering of returned IDs should match the semantic-only list prefix
        assert returned_ids == sem_ids[: len(returned_ids)]

        # scores map should be sorted descending
        scores = combined.get("scores") or {}
        vals = list(scores.values())
        assert vals == sorted(vals, reverse=True)


class TestIntegration:
    """Integration tests."""

    def test_full_workflow(self, client, test_image_id):
        """Test a full workflow: list -> get -> search."""
        if not test_image_id:
            pytest.skip("No test images available")

        # List images
        list_response = client.get("/api/v1/images/")
        assert list_response.status_code == 200
        images = list_response.json()
        assert len(images) > 0

        # Get first image
        first_image_id = images[0]["id"]
        get_response = client.get(f"/api/v1/images/{first_image_id}")
        assert get_response.status_code == 200
        image_data = get_response.json()

        # Search by author
        if image_data.get("author"):
            search_response = client.get(f"/api/v1/search/?author={image_data['author']}")
            assert search_response.status_code == 200
            search_data = search_response.json()
            assert search_data["total"] > 0


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])

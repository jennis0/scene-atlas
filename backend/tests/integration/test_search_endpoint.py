"""Integration tests for the search API endpoints.

Tests GET /api/v1/search/ (hybrid search + filters) and GET /api/v1/search/facets.
"""

import pytest

from backend.app.models.database import Color, Image, Tag

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _add_image(
    db,
    name: str,
    *,
    author: str = "TestAuthor",
    storage_key: str | None = None,
    image_type: str = "battlemap",
    media_type: str = "image",
    gridded: bool | None = None,
    group_id: int | None = None,
    search_text: str | None = None,
) -> Image:
    if storage_key is None:
        storage_key = f"{name.lower().replace(' ', '_')}.jpg"
    img = Image(
        name=name,
        filename=f"{name.replace(' ', '_')}.jpg",
        author=author,
        storage_key=storage_key,
        image_type=image_type,
        media_type=media_type,
        gridded=gridded,
        group_id=group_id,
        search_text=search_text,
    )
    db.add(img)
    db.flush()
    return img


def _add_tag(db, image: Image, category: str, value: str) -> Tag:
    tag = Tag(image_id=image.id, category=category, value=value, confidence=1.0, source="auto")
    db.add(tag)
    return tag


def _add_color(db, image: Image, hex_val: str) -> Color:
    color = Color(image_id=image.id, color_hex=hex_val, percentage=50.0, color_order=1)
    db.add(color)
    return color


@pytest.fixture
def library(test_client, tmp_db):
    """Seed a small library with varied images. Return (client, image_id_map)."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    # Author A: 3 battlemaps
    img_a1 = _add_image(
        db, "Forest Map Night", author="AuthorA", gridded=True, search_text="Forest Map Night"
    )
    _add_tag(db, img_a1, "lighting", "night")
    _add_tag(db, img_a1, "terrain", "forest")
    _add_color(db, img_a1, "#1a2b3c")

    img_a2 = _add_image(
        db, "Forest Map Day", author="AuthorA", gridded=True, search_text="Forest Map Day"
    )
    _add_tag(db, img_a2, "lighting", "day")
    _add_tag(db, img_a2, "terrain", "forest")

    img_a3 = _add_image(db, "Cave Map", author="AuthorA", gridded=False, search_text="Cave Map")
    _add_tag(db, img_a3, "terrain", "cave")

    # Author B: 2 scenes
    img_b1 = _add_image(
        db,
        "Village Scene",
        author="AuthorB",
        image_type="scene",
        gridded=None,
        search_text="Village Scene",
    )
    _add_tag(db, img_b1, "terrain", "urban")

    img_b2 = _add_image(
        db, "Market Scene", author="AuthorB", image_type="scene", search_text="Market Scene"
    )

    # Author C: 1 video
    img_c1 = _add_image(
        db,
        "Storm Video",
        author="AuthorC",
        media_type="video",
        storage_key="storm.mp4",
        search_text="Storm Video",
    )

    db.commit()
    ids = {
        "a1": img_a1.id,
        "a2": img_a2.id,
        "a3": img_a3.id,
        "b1": img_b1.id,
        "b2": img_b2.id,
        "c1": img_c1.id,
    }
    db.close()
    yield test_client, ids


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------


class TestSearchFacets:
    def test_facets_returns_required_keys(self, library):
        client, _ = library
        resp = client.get("/api/v1/search/facets")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_images" in data
        assert "authors" in data
        assert "tags" in data
        assert "gridded" in data
        assert "colors" in data
        assert "image_types" in data
        assert "media_types" in data

    def test_total_images_count(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/facets")
        assert resp.json()["total_images"] == len(ids)

    def test_authors_listed(self, library):
        client, _ = library
        authors = {a["value"] for a in client.get("/api/v1/search/facets").json()["authors"]}
        assert "AuthorA" in authors
        assert "AuthorB" in authors

    def test_tags_by_category(self, library):
        client, _ = library
        tags = client.get("/api/v1/search/facets").json()["tags"]
        assert "lighting" in tags
        assert "terrain" in tags

    def test_image_types_reported(self, library):
        client, _ = library
        types = {t["value"] for t in client.get("/api/v1/search/facets").json()["image_types"]}
        assert "battlemap" in types
        assert "scene" in types

    def test_media_types_reported(self, library):
        client, _ = library
        mtypes = {m["value"] for m in client.get("/api/v1/search/facets").json()["media_types"]}
        assert "image" in mtypes
        assert "video" in mtypes


# ---------------------------------------------------------------------------
# No-query (filter-only) search
# ---------------------------------------------------------------------------


class TestSearchNoQuery:
    def test_no_params_returns_all_images(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(ids)

    def test_results_sorted_by_name(self, library):
        client, _ = library
        resp = client.get("/api/v1/search/")
        names = [img["name"] for img in resp.json()["images"]]
        assert names == sorted(names)

    def test_author_filter_single(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"authors": ["AuthorA"]})
        assert resp.status_code == 200
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] in returned_ids
        assert ids["a2"] in returned_ids
        assert ids["a3"] in returned_ids
        assert ids["b1"] not in returned_ids

    def test_author_filter_or_logic(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"authors": ["AuthorA", "AuthorB"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] in returned_ids
        assert ids["b1"] in returned_ids
        assert ids["c1"] not in returned_ids

    def test_tag_filter_single_category(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"tags": ["lighting:night"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] in returned_ids  # has lighting:night
        assert ids["a2"] not in returned_ids  # has lighting:day

    def test_tag_filter_or_within_category(self, library):
        """Two tags in the same category → OR logic (either matches)."""
        client, ids = library
        resp = client.get("/api/v1/search/", params={"tags": ["lighting:night", "lighting:day"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] in returned_ids  # night
        assert ids["a2"] in returned_ids  # day

    def test_tag_filter_and_across_categories(self, library):
        """Tags in different categories → AND logic (both must match)."""
        client, ids = library
        resp = client.get("/api/v1/search/", params={"tags": ["lighting:night", "terrain:forest"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        # Only a1 has BOTH lighting:night AND terrain:forest
        assert ids["a1"] in returned_ids
        assert ids["a2"] not in returned_ids  # forest but day, not night
        assert ids["a3"] not in returned_ids  # cave, no lighting tag

    def test_image_type_filter_battlemap(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"image_types": ["battlemap"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] in returned_ids
        assert ids["b1"] not in returned_ids  # scene

    def test_image_type_filter_scene(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"image_types": ["scene"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["b1"] in returned_ids
        assert ids["b2"] in returned_ids
        assert ids["a1"] not in returned_ids

    def test_media_type_filter_video(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"media_types": ["video"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["c1"] in returned_ids
        assert ids["a1"] not in returned_ids

    def test_gridded_filter_true(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/?gridded=true")
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] in returned_ids  # gridded=True
        assert ids["a2"] in returned_ids  # gridded=True
        assert ids["a3"] not in returned_ids  # gridded=False

    def test_gridded_filter_false(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/?gridded=false")
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a3"] in returned_ids  # gridded=False
        assert ids["a1"] not in returned_ids  # gridded=True

    def test_exclude_author(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"exclude_authors": ["AuthorA"]})
        returned_ids = {img["id"] for img in resp.json()["images"]}
        assert ids["a1"] not in returned_ids
        assert ids["b1"] in returned_ids

    def test_pagination_offset(self, library):
        """offset skips the first N results."""
        client, ids = library
        all_resp = client.get("/api/v1/search/")
        all_ids = [img["id"] for img in all_resp.json()["images"]]

        paged_resp = client.get("/api/v1/search/?offset=2&limit=10")
        paged_ids = [img["id"] for img in paged_resp.json()["images"]]

        assert paged_ids == all_ids[2:]

    def test_pagination_limit(self, library):
        client, _ = library
        resp = client.get("/api/v1/search/?limit=2")
        assert len(resp.json()["images"]) == 2

    def test_response_schema(self, library):
        client, _ = library
        resp = client.get("/api/v1/search/")
        data = resp.json()
        assert "total" in data
        assert "images" in data
        assert "limit" in data
        assert "offset" in data


# ---------------------------------------------------------------------------
# Text search (text_only=true bypasses CLIP)
# ---------------------------------------------------------------------------


class TestSearchTextOnly:
    def test_text_search_finds_by_name(self, library):
        client, ids = library
        resp = client.get("/api/v1/search/", params={"query": "forest", "text_only": "true"})
        assert resp.status_code == 200
        returned_ids = {img["id"] for img in resp.json()["images"]}
        # Both forest maps should be found
        assert ids["a1"] in returned_ids
        assert ids["a2"] in returned_ids

    def test_text_search_no_match_returns_empty(self, library):
        client, _ = library
        resp = client.get("/api/v1/search/", params={"query": "zzznomatchxyz", "text_only": "true"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_text_search_with_author_filter(self, library):
        """Text search AND author filter must both apply."""
        client, ids = library
        resp = client.get(
            "/api/v1/search/",
            params={"query": "forest", "text_only": "true", "authors": ["AuthorA"]},
        )
        returned_ids = {img["id"] for img in resp.json()["images"]}
        # Only AuthorA's forest maps
        assert ids["a1"] in returned_ids
        assert ids["a2"] in returned_ids

    def test_fts_special_chars_do_not_crash(self, library):
        """FTS5 operator syntax in query must not cause a 500 error."""
        client, _ = library
        resp = client.get(
            "/api/v1/search/",
            params={"query": "forest AND (night OR day)", "text_only": "true"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Semantic search error handling
# ---------------------------------------------------------------------------


class TestSearchSemanticFallback:
    def test_clip_error_falls_back_gracefully(self, library, monkeypatch):
        """If CLIP raises, the endpoint must not return 500."""
        client, _ = library

        def _raise(*args, **kwargs):
            raise RuntimeError("CLIP model not loaded")

        monkeypatch.setattr("backend.app.api.search.get_clip_service", _raise)

        resp = client.get("/api/v1/search/", params={"query": "forest"})
        # Should not be 500; may return empty results if text search also fails
        assert resp.status_code == 200

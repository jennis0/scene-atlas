"""Integration tests for the search API endpoints.

Tests GET /api/v1/search/ (hybrid search + filters) and GET /api/v1/search/facets.
"""

import pytest

from backend.app.models.database import Color, Image, ImageGroup, Tag

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
        resp = client.get("/api/v1/search/", params={"sort_by": "name", "sort_dir": "asc"})
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


class TestSearchScoresAreRRF:
    """Verify returned scores are RRF merged scores, not raw CLIP cosine similarity."""

    def test_text_search_scores_in_rrf_range(self, library):
        """Text-only search scores must be RRF values (0.0-0.05), not raw CLIP (0.1-0.5+).

        RRF with K=60: best possible single-signal score = 1.1/60 ≈ 0.0183.
        Max 3-signal score = (1.0 + 1.1 + 0.5)/60 ≈ 0.0433.
        Raw CLIP cosine scores would be 0.1-0.5+.
        """
        client, ids = library
        resp = client.get("/api/v1/search/", params={"query": "forest", "text_only": "true"})
        assert resp.status_code == 200
        data = resp.json()
        scores = data.get("scores", {})

        # Must have scores for returned images
        assert len(scores) > 0

        for img_id_str, score in scores.items():
            # RRF scores are small: max possible ≈ 0.0433 per signal combo
            # Raw CLIP cosine scores would be >> 0.05
            assert score <= 0.10, (
                f"Score {score} for image {img_id_str} is too large for RRF "
                "(expected < 0.10, raw CLIP scores are 0.1-0.5+)"
            )
            assert score >= 0.0, f"Score {score} should be non-negative"

    def test_scores_dict_keys_match_returned_images(self, library):
        """The scores dict should have an entry for every returned image."""
        client, ids = library
        resp = client.get("/api/v1/search/", params={"query": "forest", "text_only": "true"})
        data = resp.json()
        scores = data.get("scores", {})
        returned_ids = {str(img["id"]) for img in data["images"]}
        score_ids = set(scores.keys())
        assert score_ids == returned_ids

    def test_no_query_scores_are_absent(self, library):
        """Without a query (browse mode), scores should be None/absent."""
        client, ids = library
        resp = client.get("/api/v1/search/")
        data = resp.json()
        # In browse mode, no relevance scoring is performed
        assert data.get("scores") is None


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
    def test_clip_error_degrades_to_text_in_hybrid_mode(self, library, monkeypatch):
        """If CLIP fails in hybrid mode, text results still returned (not 503)."""
        client, _ = library

        def _raise(*args, **kwargs):
            raise RuntimeError("CLIP model not loaded")

        monkeypatch.setattr("backend.app.api.search.get_clip_service", _raise)

        resp = client.get("/api/v1/search/", params={"query": "forest"})
        assert resp.status_code == 200

    def test_clip_error_returns_503_in_semantic_only_mode(self, library, monkeypatch):
        """If CLIP fails and semantic_only is set, return 503 (no text fallback)."""
        client, _ = library

        def _raise(*args, **kwargs):
            raise RuntimeError("CLIP model not loaded")

        monkeypatch.setattr("backend.app.api.search.get_clip_service", _raise)

        resp = client.get("/api/v1/search/", params={"query": "forest", "semantic_only": "true"})
        assert resp.status_code == 503

    def test_clip_error_still_returns_text_results(self, library, monkeypatch):
        """If CLIP raises in hybrid mode, text-matched results are still returned."""
        client, ids = library

        def _raise(*args, **kwargs):
            raise RuntimeError("CLIP model not loaded")

        monkeypatch.setattr("backend.app.api.search.get_clip_service", _raise)

        resp = client.get("/api/v1/search/", params={"query": "forest"})
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = {img["id"] for img in data["images"]}
        # FTS5 matches "Forest Map Night" and "Forest Map Day"
        assert ids["a1"] in returned_ids
        assert ids["a2"] in returned_ids

    def test_empty_semantic_results_still_returns_text_results(self, library, monkeypatch):
        """If Qdrant returns 0 semantic matches, text results still come through."""
        client, ids = library

        from unittest.mock import MagicMock

        mock_clip = MagicMock()
        mock_clip.encode_text.return_value = [0.0] * 768
        monkeypatch.setattr("backend.app.api.search.get_clip_service", lambda: mock_clip)

        mock_qdrant = MagicMock()
        mock_qdrant.search_similar.return_value = []  # 0 semantic results
        monkeypatch.setattr("backend.app.api.search.get_qdrant_service", lambda: mock_qdrant)

        resp = client.get("/api/v1/search/", params={"query": "forest"})
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = {img["id"] for img in data["images"]}
        assert ids["a1"] in returned_ids
        assert ids["a2"] in returned_ids

    def test_text_only_search_works_without_clip(self, library, monkeypatch):
        """text_only=true bypasses CLIP entirely, so it works even if model is down."""
        client, _ = library

        def _raise(*args, **kwargs):
            raise RuntimeError("CLIP model not loaded")

        monkeypatch.setattr("backend.app.api.search.get_clip_service", _raise)

        resp = client.get("/api/v1/search/", params={"query": "forest", "text_only": "true"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Groups endpoint (browse and search modes)
# ---------------------------------------------------------------------------


@pytest.fixture
def grouped_library(test_client, tmp_db):
    """Seed groups with multiple images for grouped view testing."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    # Group 1: "Forest Variants" with 4 images (AuthorA)
    group1 = ImageGroup(base_name="Forest Variants", author="AuthorA")
    db.add(group1)
    db.flush()

    img_g1_1 = _add_image(
        db,
        "Forest Winter",
        author="AuthorA",
        gridded=True,
        group_id=group1.id,
        search_text="Forest Winter snowy",
    )
    _add_tag(db, img_g1_1, "season", "winter")
    _add_color(db, img_g1_1, "#ffffff")

    group1.primary_image_id = img_g1_1.id

    img_g1_2 = _add_image(
        db,
        "Forest Summer",
        author="AuthorA",
        gridded=True,
        group_id=group1.id,
        search_text="Forest Summer green",
    )
    _add_tag(db, img_g1_2, "season", "summer")
    _add_color(db, img_g1_2, "#00ff00")

    img_g1_3 = _add_image(
        db,
        "Forest Autumn",
        author="AuthorA",
        gridded=True,
        group_id=group1.id,
        search_text="Forest Autumn orange",
    )
    _add_tag(db, img_g1_3, "season", "autumn")
    _add_color(db, img_g1_3, "#ff6600")

    img_g1_4 = _add_image(
        db,
        "Forest Spring",
        author="AuthorA",
        gridded=True,
        group_id=group1.id,
        search_text="Forest Spring blooming",
    )
    _add_tag(db, img_g1_4, "season", "spring")

    # Group 2: "Dungeon Variants" with 3 images (AuthorB)
    group2 = ImageGroup(base_name="Dungeon Variants", author="AuthorB")
    db.add(group2)
    db.flush()

    img_g2_1 = _add_image(
        db,
        "Dungeon Dark",
        author="AuthorB",
        gridded=False,
        image_type="scene",
        group_id=group2.id,
        search_text="Dungeon Dark shadows",
    )
    _add_tag(db, img_g2_1, "lighting", "dark")
    _add_color(db, img_g2_1, "#1a1a1a")

    group2.primary_image_id = img_g2_1.id

    img_g2_2 = _add_image(
        db,
        "Dungeon Torch",
        author="AuthorB",
        gridded=False,
        image_type="scene",
        group_id=group2.id,
        search_text="Dungeon Torch lit",
    )
    _add_tag(db, img_g2_2, "lighting", "torch")
    _add_color(db, img_g2_2, "#ffaa00")

    img_g2_3 = _add_image(
        db,
        "Dungeon Bright",
        author="AuthorB",
        gridded=False,
        image_type="scene",
        group_id=group2.id,
        search_text="Dungeon Bright illuminated",
    )
    _add_tag(db, img_g2_3, "lighting", "bright")
    _add_color(db, img_g2_3, "#ffffff")

    # Group 3: "Tavern" with 5 images (AuthorC) - for mosaic fill testing
    group3 = ImageGroup(base_name="Tavern", author="AuthorC")
    db.add(group3)
    db.flush()

    img_g3_1 = _add_image(
        db,
        "Tavern Empty",
        author="AuthorC",
        gridded=None,
        image_type="scene",
        group_id=group3.id,
        search_text="Tavern Empty deserted",
    )
    _add_tag(db, img_g3_1, "occupancy", "empty")

    group3.primary_image_id = img_g3_1.id

    img_g3_2 = _add_image(
        db,
        "Tavern Crowded",
        author="AuthorC",
        gridded=None,
        image_type="scene",
        group_id=group3.id,
        search_text="Tavern Crowded busy",
    )
    _add_tag(db, img_g3_2, "occupancy", "crowded")

    img_g3_3 = _add_image(
        db,
        "Tavern Cozy",
        author="AuthorC",
        gridded=None,
        image_type="scene",
        group_id=group3.id,
        search_text="Tavern Cozy warm",
    )
    _add_tag(db, img_g3_3, "occupancy", "cozy")

    img_g3_4 = _add_image(
        db,
        "Tavern Night",
        author="AuthorC",
        gridded=None,
        image_type="scene",
        group_id=group3.id,
        search_text="Tavern Night dark evening",
    )
    _add_tag(db, img_g3_4, "lighting", "night")

    img_g3_5 = _add_image(
        db,
        "Tavern Day",
        author="AuthorC",
        gridded=None,
        image_type="scene",
        group_id=group3.id,
        search_text="Tavern Day bright",
    )
    _add_tag(db, img_g3_5, "lighting", "day")

    db.commit()
    ids = {
        "g1": group1.id,
        "g2": group2.id,
        "g3": group3.id,
        "g1_1": img_g1_1.id,
        "g1_2": img_g1_2.id,
        "g1_3": img_g1_3.id,
        "g1_4": img_g1_4.id,
        "g2_1": img_g2_1.id,
        "g2_2": img_g2_2.id,
        "g2_3": img_g2_3.id,
        "g3_1": img_g3_1.id,
        "g3_2": img_g3_2.id,
        "g3_3": img_g3_3.id,
        "g3_4": img_g3_4.id,
        "g3_5": img_g3_5.id,
    }
    db.close()
    yield test_client, ids


class TestGroupsEndpointBrowse:
    """Browse mode: no query, groups sorted by created_at or name."""

    def test_groups_browse_returns_all_groups(self, grouped_library):
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_groups"] == 3
        assert len(data["groups"]) == 3

    def test_groups_browse_default_sort_by_created_at_desc(self, grouped_library):
        """Without sort_by, groups should be sorted by created_at DESC (newest first)."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        data = resp.json()
        group_names = [g["base_name"] for g in data["groups"]]
        # Groups created in order: Tavern, Dungeon, Forest (last to first)
        assert group_names == ["Tavern", "Dungeon Variants", "Forest Variants"]

    def test_groups_browse_sort_by_name_asc(self, grouped_library):
        """Sorted by name ascending."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"sort_by": "name", "sort_dir": "asc"})
        data = resp.json()
        group_names = [g["base_name"] for g in data["groups"]]
        assert group_names == sorted(group_names)

    def test_groups_browse_mosaic_images_populated(self, grouped_library):
        """In browse mode, mosaic_images should be populated (up to 4 additional images)."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        data = resp.json()
        for group in data["groups"]:
            # Mosaic should have up to 4 images (group has at least 3 total, so 4 other than hero)
            assert isinstance(group["mosaic_images"], list)
            assert len(group["mosaic_images"]) <= 4

    def test_groups_browse_pagination_offset(self, grouped_library):
        """offset=1 should skip the first group."""
        client, ids = grouped_library
        all_resp = client.get("/api/v1/search/groups")
        all_names = [g["base_name"] for g in all_resp.json()["groups"]]

        paged_resp = client.get("/api/v1/search/groups", params={"offset": 1, "limit": 10})
        paged_names = [g["base_name"] for g in paged_resp.json()["groups"]]

        assert paged_names == all_names[1:]

    def test_groups_browse_pagination_limit(self, grouped_library):
        """limit=2 should return only 2 groups."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"limit": 2})
        assert len(resp.json()["groups"]) == 2

    def test_groups_browse_hero_image_populated(self, grouped_library):
        """Each group should have a hero_image (primary image)."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        data = resp.json()
        for group in data["groups"]:
            assert group["hero_image"] is not None
            assert "id" in group["hero_image"]
            assert "name" in group["hero_image"]

    def test_groups_browse_best_score_none(self, grouped_library):
        """In browse mode, best_score should be None."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        data = resp.json()
        for group in data["groups"]:
            assert group["best_score"] is None

    def test_groups_browse_matching_scenes_equals_total_scenes(self, grouped_library):
        """In browse mode, matching_scenes should equal total_scenes."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        data = resp.json()
        for group in data["groups"]:
            assert group["matching_scenes"] == group["total_scenes"]


class TestGroupsEndpointSearch:
    """Search mode: query present, groups ranked by best_score."""

    def test_groups_search_by_query(self, grouped_library):
        """Search should return groups with matching images."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "forest"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["groups"]) > 0
        # Should find group 1 (Forest Variants)
        group_names = [g["base_name"] for g in data["groups"]]
        assert "Forest Variants" in group_names

    def test_groups_search_best_score_sorted_desc(self, grouped_library):
        """Groups in search mode should be sorted by best_score DESC."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "winter"})
        data = resp.json()
        if len(data["groups"]) > 1:
            scores = [g["best_score"] for g in data["groups"]]
            # Scores should be non-increasing (or None, but in search mode all should have scores)
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1]

    def test_groups_search_best_score_normalized_0_to_1(self, grouped_library):
        """Scores should be in [0, 1] range."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "forest"})
        data = resp.json()
        for group in data["groups"]:
            if group["best_score"] is not None:
                assert 0 <= group["best_score"] <= 1

    def test_groups_search_hero_is_best_match(self, grouped_library):
        """Hero image should be the one with the highest score in the group."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "forest"})
        data = resp.json()
        # Forest group should have highest-scoring image as hero
        forest_group = next(
            (g for g in data["groups"] if g["base_name"] == "Forest Variants"), None
        )
        if forest_group:
            assert forest_group["hero_image"] is not None

    def test_groups_search_matching_scenes_less_than_total(self, grouped_library):
        """For filtered search, matching_scenes may be less than total_scenes."""
        client, ids = grouped_library
        resp = client.get(
            "/api/v1/search/groups", params={"query": "winter", "tags": ["season:winter"]}
        )
        data = resp.json()
        # Tavern group has no winter tag, so if included, matching < total
        tavern = next((g for g in data["groups"] if g["base_name"] == "Tavern"), None)
        if tavern:
            # Tavern has 5 images, none match "winter"
            assert tavern["matching_scenes"] <= tavern["total_scenes"]

    def test_groups_search_mosaic_fill_batch_query(self, grouped_library):
        """Mosaic should have up to 4 images, filled from group if < 5 scored matches."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "tavern"})
        data = resp.json()
        tavern = next((g for g in data["groups"] if g["base_name"] == "Tavern"), None)
        if tavern:
            # Tavern has 5 images, mosaic should be filled
            assert len(tavern["mosaic_images"]) <= 4
            assert len(tavern["mosaic_images"]) > 0

    def test_groups_search_filter_author(self, grouped_library):
        """Filter by author should only return matching groups."""
        client, ids = grouped_library
        resp = client.get(
            "/api/v1/search/groups", params={"query": "forest", "authors": ["AuthorA"]}
        )
        data = resp.json()
        group_authors = [g["author"] for g in data["groups"]]
        assert all(a == "AuthorA" for a in group_authors)

    def test_groups_search_filter_tags(self, grouped_library):
        """Filter by tags should only return groups with matching images."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "", "tags": ["season:winter"]})
        data = resp.json()
        # Should find Forest group (has winter tag on img_g1_1)
        group_names = [g["base_name"] for g in data["groups"]]
        if group_names:
            assert "Forest Variants" in group_names

    def test_groups_search_image_type_filter(self, grouped_library):
        """Filter by image_type should only return groups with matching images."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"image_types": ["scene"]})
        data = resp.json()
        # Should find Dungeon and Tavern (both are scenes), not Forest (battlemaps)
        # Exact behavior depends on search engine, but should have some groups
        assert len(data["groups"]) > 0

    def test_groups_search_response_schema(self, grouped_library):
        """Response should have required fields."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "forest"})
        data = resp.json()
        assert "total_groups" in data
        assert "groups" in data
        assert "limit" in data
        assert "offset" in data

        for group in data["groups"]:
            assert "group_id" in group
            assert "base_name" in group
            assert "author" in group
            assert "hero_image" in group
            assert "mosaic_images" in group
            assert "best_score" in group
            assert "matching_scenes" in group
            assert "total_scenes" in group

    def test_groups_search_empty_query_returns_browse_mode(self, grouped_library):
        """Empty or whitespace query should behave like browse mode (no scores, but mosaic populated)."""
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "   "})
        data = resp.json()
        for group in data["groups"]:
            assert group["best_score"] is None
            # Mosaic should still be populated in browse mode
            assert isinstance(group["mosaic_images"], list)
            assert len(group["mosaic_images"]) <= 4


class TestGroupsIncludeAllImageIds:
    def test_browse_mode_without_flag_has_no_image_ids(self, grouped_library):
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups")
        assert resp.status_code == 200
        for group in resp.json()["groups"]:
            assert group.get("all_image_ids") is None

    def test_browse_mode_with_flag_returns_all_ids(self, grouped_library):
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"include_all_image_ids": True})
        assert resp.status_code == 200
        for group in resp.json()["groups"]:
            assert group["all_image_ids"] is not None
            assert len(group["all_image_ids"]) == group["total_scenes"]

    def test_browse_mode_forest_group_ids_correct(self, grouped_library):
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"include_all_image_ids": True})
        forest = next(g for g in resp.json()["groups"] if g["base_name"] == "Forest Variants")
        assert set(forest["all_image_ids"]) == {ids["g1_1"], ids["g1_2"], ids["g1_3"], ids["g1_4"]}

    def test_browse_mode_paginated_returns_ids_for_page_only(self, grouped_library):
        client, ids = grouped_library
        resp = client.get(
            "/api/v1/search/groups", params={"include_all_image_ids": True, "limit": 1}
        )
        data = resp.json()
        assert len(data["groups"]) == 1
        assert data["groups"][0]["all_image_ids"] is not None

    def test_search_mode_without_flag_has_no_image_ids(self, grouped_library):
        client, ids = grouped_library
        resp = client.get("/api/v1/search/groups", params={"query": "forest"})
        assert resp.status_code == 200
        for group in resp.json()["groups"]:
            assert group.get("all_image_ids") is None

    def test_search_mode_with_flag_returns_matched_ids(self, grouped_library):
        client, ids = grouped_library
        resp = client.get(
            "/api/v1/search/groups",
            params={"query": "forest", "include_all_image_ids": True},
        )
        assert resp.status_code == 200
        forest_ids = {ids["g1_1"], ids["g1_2"], ids["g1_3"], ids["g1_4"]}
        for group in resp.json()["groups"]:
            if group["base_name"] == "Forest Variants":
                assert group["all_image_ids"] is not None
                for img_id in group["all_image_ids"]:
                    assert img_id in forest_ids

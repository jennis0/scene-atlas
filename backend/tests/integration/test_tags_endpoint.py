"""Integration tests for the tags API endpoints.

Tests GET/POST/PATCH/DELETE /api/v1/tags/* — categories, tag values, per-image ops.
"""

import pytest

from backend.app.models.database import Image, ImageGroup, Tag, TagCategory

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_image(db, name: str, storage_key: str) -> Image:
    group = ImageGroup(base_name=name, author="TestAuthor")
    db.add(group)
    db.flush()
    img = Image(
        name=name,
        filename=f"{name}.jpg",
        author="TestAuthor",
        storage_key=storage_key,
        group_id=group.id,
        media_type="image",
        image_type="battlemap",
    )
    db.add(img)
    db.flush()
    return img


@pytest.fixture
def seeded_category(test_client, tmp_db):
    """Create a fresh tag category (unique name) with two known values."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    cat = TagCategory(
        name="test_biome",
        description="Biome type (test-only)",
        color="#00ff00",
        display_order=99,
        common_values='[{"value": "forest", "aliases": []}, {"value": "desert", "aliases": []}]',
    )
    db.add(cat)
    db.commit()
    cat_name = cat.name
    db.close()

    yield test_client, cat_name


@pytest.fixture
def seeded_image_with_tags(test_client, tmp_db):
    """Create an image with two tags attached."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    img = _make_image(db, "TaggedMap", "tagged_map.jpg")
    # Ensure TagCategory rows exist (endpoints look up categories by name)
    for cat_name, values in (
        ("lighting", '[{"value": "night", "aliases": []}]'),
        ("terrain", '[{"value": "forest", "aliases": []}]'),
    ):
        if not db.query(TagCategory).filter(TagCategory.name == cat_name).first():
            db.add(TagCategory(name=cat_name, display_order=0, common_values=values))
    db.flush()
    tag1 = Tag(image_id=img.id, category="lighting", value="night", confidence=1.0, source="manual")
    tag2 = Tag(image_id=img.id, category="terrain", value="forest", confidence=0.9, source="auto")
    db.add_all([tag1, tag2])
    db.commit()
    data = {"image_id": img.id, "tag1_id": tag1.id, "tag2_id": tag2.id}
    db.close()

    yield test_client, data


# ---------------------------------------------------------------------------
# GET /api/v1/tags/categories
# ---------------------------------------------------------------------------


class TestListCategories:
    def test_returns_list(self, test_client):
        resp = test_client.get("/api/v1/tags/categories")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_seeded_categories_present(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.get("/api/v1/tags/categories")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert cat_name in names


# ---------------------------------------------------------------------------
# POST /api/v1/tags/categories
# ---------------------------------------------------------------------------


class TestCreateCategory:
    def test_create_new_category(self, test_client):
        resp = test_client.post(
            "/api/v1/tags/categories",
            json={
                "name": "test_atmosphere",
                "description": "Test category",
                "color": "#0000ff",
                "display_order": 98,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test_atmosphere"
        assert data["color"] == "#0000ff"

    def test_duplicate_name_returns_409(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.post(
            "/api/v1/tags/categories",
            json={"name": cat_name},
        )
        assert resp.status_code == 409

    def test_created_category_retrievable(self, test_client):
        test_client.post("/api/v1/tags/categories", json={"name": "newcat99"})
        resp = test_client.get("/api/v1/tags/categories/newcat99")
        assert resp.status_code == 200
        assert resp.json()["name"] == "newcat99"


# ---------------------------------------------------------------------------
# GET /api/v1/tags/categories/{category_name}
# ---------------------------------------------------------------------------


class TestGetCategory:
    def test_returns_existing_category(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.get(f"/api/v1/tags/categories/{cat_name}")
        assert resp.status_code == 200
        assert resp.json()["name"] == cat_name

    def test_missing_category_returns_404(self, test_client):
        resp = test_client.get("/api/v1/tags/categories/zzznobody")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/tags/categories/{category_name}
# ---------------------------------------------------------------------------


class TestUpdateCategory:
    def test_update_description(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.patch(
            f"/api/v1/tags/categories/{cat_name}",
            json={"description": "Updated description"},
        )
        assert resp.status_code == 200
        assert resp.json()["category"]["description"] == "Updated description"

    def test_rename_category_cascades_to_tags(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.patch(
            "/api/v1/tags/categories/lighting",
            json={"name": "illumination"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["category"]["name"] == "illumination"
        # The one image with a lighting tag should be affected
        assert result["affected_images"] >= 1

        # Old category name should be gone
        assert client.get("/api/v1/tags/categories/lighting").status_code == 404
        assert client.get("/api/v1/tags/categories/illumination").status_code == 200

    def test_rename_to_existing_name_returns_409(self, seeded_category):
        client, cat_name = seeded_category
        # Create a second category then try to rename first to it
        client.post("/api/v1/tags/categories", json={"name": "conflict_cat"})
        resp = client.patch(
            f"/api/v1/tags/categories/{cat_name}",
            json={"name": "conflict_cat"},
        )
        assert resp.status_code == 409

    def test_update_missing_category_returns_404(self, test_client):
        resp = test_client.patch(
            "/api/v1/tags/categories/zzznobody",
            json={"description": "x"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/tags/categories/{category_name}
# ---------------------------------------------------------------------------


class TestDeleteCategory:
    def test_delete_removes_category(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.delete(f"/api/v1/tags/categories/{cat_name}")
        assert resp.status_code == 200
        assert client.get(f"/api/v1/tags/categories/{cat_name}").status_code == 404

    def test_delete_cascades_to_image_tags(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        # Delete the "terrain" category — tag2 is in terrain
        resp = client.delete("/api/v1/tags/categories/terrain")
        assert resp.status_code == 200
        result = resp.json()
        assert result["deleted_tags"] >= 1
        # The terrain tag on the image should be gone
        tags_resp = client.get(f"/api/v1/tags/image/{data['image_id']}")
        values = [(t["category"], t["value"]) for t in tags_resp.json()]
        assert ("terrain", "forest") not in values

    def test_delete_missing_category_returns_404(self, test_client):
        resp = test_client.delete("/api/v1/tags/categories/zzznobody")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/tags/categories/{category_name}/tags/{tag_name}  (upsert value)
# ---------------------------------------------------------------------------


class TestUpsertTagValue:
    def test_add_new_value_to_category(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.put(f"/api/v1/tags/categories/{cat_name}/tags/jungle")
        assert resp.status_code == 200
        values_raw = resp.json()["common_values"]
        import json

        values = [v["value"] if isinstance(v, dict) else v for v in json.loads(values_raw)]
        assert "jungle" in values

    def test_update_aliases_on_existing_value(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.put(
            f"/api/v1/tags/categories/{cat_name}/tags/forest",
            content='["woods", "trees"]',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_upsert_missing_category_returns_404(self, test_client):
        resp = test_client.put("/api/v1/tags/categories/zzznobody/tags/val")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/tags/categories/{category_name}/tags/{tag_name}  (rename value)
# ---------------------------------------------------------------------------


class TestRenameTagValue:
    def test_rename_value_in_vocabulary(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.patch(
            f"/api/v1/tags/categories/{cat_name}/tags/forest",
            json={"new_value": "woodland"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["old_value"] == "forest"
        assert result["new_value"] == "woodland"

    def test_rename_cascades_to_image_tags(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        # terrain/forest → terrain/woodland
        resp = client.patch(
            "/api/v1/tags/categories/terrain/tags/forest",
            json={"new_value": "woodland"},
        )
        assert resp.status_code == 200
        assert resp.json()["affected_images"] >= 1
        # Verify the tag on the image was updated
        tags = client.get(f"/api/v1/tags/image/{data['image_id']}").json()
        values = [(t["category"], t["value"]) for t in tags]
        assert ("terrain", "woodland") in values
        assert ("terrain", "forest") not in values

    def test_rename_missing_value_returns_404(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.patch(
            f"/api/v1/tags/categories/{cat_name}/tags/zzznoval",
            json={"new_value": "x"},
        )
        assert resp.status_code == 404

    def test_rename_missing_category_returns_404(self, test_client):
        resp = test_client.patch(
            "/api/v1/tags/categories/zzznobody/tags/forest",
            json={"new_value": "x"},
        )
        assert resp.status_code == 404

    def test_rename_empty_value_returns_400(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.patch(
            f"/api/v1/tags/categories/{cat_name}/tags/forest",
            json={"new_value": "   "},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/v1/tags/categories/{category_name}/tags/{tag_name}  (delete value)
# ---------------------------------------------------------------------------


class TestDeleteTagValue:
    def test_delete_value_from_vocabulary(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.delete(f"/api/v1/tags/categories/{cat_name}/tags/desert")
        assert resp.status_code == 200
        result = resp.json()
        assert "desert" in result["message"]

    def test_delete_cascades_to_image_tags(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.delete("/api/v1/tags/categories/terrain/tags/forest")
        assert resp.status_code == 200
        assert resp.json()["deleted_tags"] >= 1
        tags = client.get(f"/api/v1/tags/image/{data['image_id']}").json()
        assert not any(t["value"] == "forest" and t["category"] == "terrain" for t in tags)

    def test_delete_missing_value_returns_404(self, seeded_category):
        client, cat_name = seeded_category
        resp = client.delete(f"/api/v1/tags/categories/{cat_name}/tags/zzznoval")
        assert resp.status_code == 404

    def test_delete_value_missing_category_returns_404(self, test_client):
        resp = test_client.delete("/api/v1/tags/categories/zzznobody/tags/val")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/tags/values/{category_name}
# ---------------------------------------------------------------------------


class TestGetTagValuesForCategory:
    def test_returns_used_values(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.get("/api/v1/tags/values/lighting")
        assert resp.status_code == 200
        result = resp.json()
        assert result["category"] == "lighting"
        assert "night" in result["values"]

    def test_empty_category_returns_empty_list(self, seeded_category):
        client, cat_name = seeded_category
        # terrain category has vocabulary but no images tagged with it yet
        resp = client.get(f"/api/v1/tags/values/{cat_name}")
        assert resp.status_code == 200
        assert resp.json()["values"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/tags/image/{image_id}
# ---------------------------------------------------------------------------


class TestGetImageTags:
    def test_returns_tags_for_image(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.get(f"/api/v1/tags/image/{data['image_id']}")
        assert resp.status_code == 200
        tags = resp.json()
        assert len(tags) == 2

    def test_returns_empty_for_untagged_image(self, test_client, tmp_db):
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        img = _make_image(db, "Untagged", "untagged.jpg")
        db.commit()
        img_id = img.id
        db.close()

        resp = test_client.get(f"/api/v1/tags/image/{img_id}")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/v1/tags/image/{image_id}
# ---------------------------------------------------------------------------


class TestAddTagToImage:
    def test_add_tag(self, test_client, tmp_db):
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        img = _make_image(db, "FreshMap", "fresh_map.jpg")
        db.commit()
        img_id = img.id
        db.close()

        resp = test_client.post(
            f"/api/v1/tags/image/{img_id}",
            json={"category": "lighting", "value": "dawn", "confidence": 0.8, "source": "manual"},
        )
        assert resp.status_code == 200
        tag = resp.json()
        assert tag["category"] == "lighting"
        assert tag["value"] == "dawn"
        assert tag["image_id"] == img_id


# ---------------------------------------------------------------------------
# DELETE /api/v1/tags/{tag_id}
# ---------------------------------------------------------------------------


class TestDeleteTag:
    def test_delete_existing_tag(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.delete(f"/api/v1/tags/{data['tag1_id']}")
        assert resp.status_code == 200
        # Confirm tag is gone
        tags = client.get(f"/api/v1/tags/image/{data['image_id']}").json()
        assert not any(t["id"] == data["tag1_id"] for t in tags)

    def test_delete_missing_tag_returns_404(self, test_client):
        resp = test_client.delete("/api/v1/tags/999999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/tags/stats
# ---------------------------------------------------------------------------


class TestTagStatistics:
    def test_returns_stats_shape(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.get("/api/v1/tags/stats")
        assert resp.status_code == 200
        result = resp.json()
        assert "total_tags" in result
        assert "categories" in result
        assert result["total_tags"] >= 2

    def test_category_breakdown_present(self, seeded_image_with_tags):
        client, data = seeded_image_with_tags
        resp = client.get("/api/v1/tags/stats")
        categories = resp.json()["categories"]
        assert "lighting" in categories
        assert categories["lighting"]["total_tags"] >= 1


# ---------------------------------------------------------------------------
# POST /api/v1/tags/packs/import-multiple
# ---------------------------------------------------------------------------


class TestImportMultipleTagPacks:
    def test_import_multiple_returns_200(self, test_client, tmp_db):
        # Clear categories so packs have something to import
        engine, SessionLocal = tmp_db
        db = SessionLocal()
        db.query(TagCategory).delete()
        db.commit()
        db.close()

        resp = test_client.post(
            "/api/v1/tags/packs/import-multiple",
            json={"packs": ["common", "fantasy"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "common" in data["imported"]
        assert "fantasy" in data["imported"]
        assert data["errors"] == []

    def test_import_multiple_empty_list(self, test_client):
        resp = test_client.post(
            "/api/v1/tags/packs/import-multiple",
            json={"packs": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == []
        assert data["errors"] == []

    def test_import_multiple_with_invalid_pack(self, test_client):
        resp = test_client.post(
            "/api/v1/tags/packs/import-multiple",
            json={"packs": ["common", "nonexistent_pack"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "common" in data["imported"]
        assert len(data["errors"]) == 1
        assert "nonexistent_pack" in data["errors"][0]

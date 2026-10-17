"""Integration tests for the groups API endpoints.

Tests GET/PUT/DELETE /api/v1/groups/* and POST /api/v1/groups/{id}/merge
and POST /api/v1/groups/{id}/move-images.
"""

import pytest

from backend.app.models.database import Image, ImageGroup

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_group(db_session, base_name: str, author: str = "TestAuthor") -> ImageGroup:
    group = ImageGroup(base_name=base_name, author=author)
    db_session.add(group)
    db_session.flush()  # get group.id without committing
    return group


def _make_image(
    db_session,
    group: ImageGroup,
    name: str,
    *,
    storage_key: str | None = None,
    subgroup: str | None = None,
) -> Image:
    if storage_key is None:
        storage_key = f"{name.lower().replace(' ', '_')}.jpg"
    img = Image(
        name=name,
        filename=f"{name.replace(' ', '_')}.jpg",
        author=group.author,
        storage_key=storage_key,
        group_id=group.id,
        media_type="image",
        image_type="battlemap",
        subgroup=subgroup,
    )
    db_session.add(img)
    db_session.flush()
    return img


@pytest.fixture
def seeded_group(test_client, tmp_db):
    """Create one ImageGroup with 3 images, return (client, group, images)."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    group = _make_group(db, "Ancient Ruins")
    img1 = _make_image(db, group, "Ancient Ruins Day", storage_key="ruins_day.jpg")
    img2 = _make_image(
        db, group, "Ancient Ruins Night", storage_key="ruins_night.jpg", subgroup="Night"
    )
    img3 = _make_image(
        db, group, "Ancient Ruins Winter", storage_key="ruins_winter.jpg", subgroup="Winter"
    )
    group.primary_image_id = img1.id
    db.commit()

    group_id = group.id
    img_ids = [img1.id, img2.id, img3.id]
    db.close()

    yield test_client, group_id, img_ids


@pytest.fixture
def two_groups(test_client, tmp_db):
    """Create two ImageGroups for merge testing."""
    engine, SessionLocal = tmp_db
    db = SessionLocal()

    source = _make_group(db, "Forest Path", author="AuthorA")
    img_s1 = _make_image(db, source, "Forest Path Day", storage_key="fp_day.jpg")
    img_s2 = _make_image(db, source, "Forest Path Night", storage_key="fp_night.jpg")
    source.primary_image_id = img_s1.id

    target = _make_group(db, "Forest Cave", author="AuthorB")
    img_t1 = _make_image(db, target, "Forest Cave Main", storage_key="fc_main.jpg")
    target.primary_image_id = img_t1.id

    db.commit()

    data = {
        "source_id": source.id,
        "target_id": target.id,
        "source_img_ids": [img_s1.id, img_s2.id],
        "target_img_ids": [img_t1.id],
    }
    db.close()

    yield test_client, data


# ---------------------------------------------------------------------------
# GET /api/v1/groups/search
# ---------------------------------------------------------------------------


class TestGroupSearch:
    def test_empty_query_returns_all_groups(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.get("/api/v1/groups/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        ids = [g["id"] for g in data["groups"]]
        assert group_id in ids

    def test_name_filter_narrows_results(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.get("/api/v1/groups/search?q=Ancient")
        assert resp.status_code == 200
        data = resp.json()
        ids = [g["id"] for g in data["groups"]]
        assert group_id in ids

    def test_name_filter_no_match_returns_empty(self, seeded_group):
        client, _, _ = seeded_group
        resp = client.get("/api/v1/groups/search?q=zzznomatch")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_exclude_id_omits_group(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.get(f"/api/v1/groups/search?exclude_id={group_id}")
        assert resp.status_code == 200
        ids = [g["id"] for g in resp.json()["groups"]]
        assert group_id not in ids

    def test_reference_name_sorts_by_jaccard(self, two_groups):
        """Groups ranked higher when reference_name is more similar to their base_name."""
        client, data = two_groups
        # "Forest Path" should rank higher than "Forest Cave" for reference "Forest Path"
        resp = client.get("/api/v1/groups/search?reference_name=Forest+Path")
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        assert len(groups) >= 2
        names = [g["base_name"] for g in groups]
        assert names.index("Forest Path") < names.index("Forest Cave")

    def test_image_count_included(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.get("/api/v1/groups/search?q=Ancient")
        assert resp.status_code == 200
        group_data = next(g for g in resp.json()["groups"] if g["id"] == group_id)
        assert group_data["image_count"] == len(img_ids)


# ---------------------------------------------------------------------------
# GET /api/v1/groups/{id}
# ---------------------------------------------------------------------------


class TestGroupDetail:
    def test_returns_group_with_images(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.get(f"/api/v1/groups/{group_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == group_id
        assert data["base_name"] == "Ancient Ruins"
        returned_ids = [img["id"] for img in data["images"]]
        for img_id in img_ids:
            assert img_id in returned_ids

    def test_missing_group_returns_404(self, seeded_group):
        client, _, _ = seeded_group
        resp = client.get("/api/v1/groups/999999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/groups/{id}
# ---------------------------------------------------------------------------


class TestGroupEdit:
    def test_rename_group(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Renamed Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_id,
                        "name": f"img{img_id}",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    }
                    for img_id in img_ids
                ],
                "new_groups": [],
            },
        )
        assert resp.status_code == 200
        # Verify the rename persisted
        detail = client.get(f"/api/v1/groups/{group_id}").json()
        assert detail["base_name"] == "Renamed Ruins"

    def test_delete_one_image_from_group(self, seeded_group):
        client, group_id, img_ids = seeded_group
        # Keep only 2 of 3 images
        kept_ids = img_ids[:2]
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_id,
                        "name": f"img{img_id}",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    }
                    for img_id in kept_ids
                ],
                "new_groups": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert img_ids[2] in data["deleted_image_ids"]

        # Group still exists with 2 images
        detail = client.get(f"/api/v1/groups/{group_id}").json()
        assert len(detail["images"]) == 2

    def test_update_author(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "NewAuthor",
                "images": [
                    {
                        "id": img_id,
                        "name": f"img{img_id}",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    }
                    for img_id in img_ids
                ],
                "new_groups": [],
            },
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/v1/groups/{group_id}").json()
        assert detail["author"] == "NewAuthor"

    def test_update_image_tags(self, seeded_group):
        client, group_id, img_ids = seeded_group
        tag = {"category": "lighting", "value": "night", "confidence": 1.0, "source": "manual"}
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_ids[0],
                        "name": "img0",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [tag],
                    },
                    *[
                        {
                            "id": img_id,
                            "name": f"img{img_id}",
                            "gridded": None,
                            "grid_width": None,
                            "grid_height": None,
                            "subgroup": None,
                            "image_type": None,
                            "tags": [],
                        }
                        for img_id in img_ids[1:]
                    ],
                ],
                "new_groups": [],
            },
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/v1/groups/{group_id}").json()
        img0 = next(img for img in detail["images"] if img["id"] == img_ids[0])
        assert any(t["value"] == "night" for t in img0["tags"])

    def test_missing_group_returns_404(self, seeded_group):
        client, _, _ = seeded_group
        resp = client.put(
            "/api/v1/groups/999999",
            json={"base_name": "X", "author": "A", "images": [], "new_groups": []},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/groups/{id}/merge
# ---------------------------------------------------------------------------


class TestGroupMerge:
    def test_merge_moves_images_to_target(self, two_groups):
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]

        resp = client.post(
            f"/api/v1/groups/{source_id}/merge",
            json={"target_group_id": target_id},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["target_group_id"] == target_id
        assert result["images_moved"] == len(data["source_img_ids"])
        assert result["source_group_deleted"] is True

    def test_merge_deletes_source_group(self, two_groups):
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]

        client.post(f"/api/v1/groups/{source_id}/merge", json={"target_group_id": target_id})

        # Source must no longer exist
        resp = client.get(f"/api/v1/groups/{source_id}")
        assert resp.status_code == 404

    def test_merge_images_appear_in_target(self, two_groups):
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]

        client.post(f"/api/v1/groups/{source_id}/merge", json={"target_group_id": target_id})

        detail = client.get(f"/api/v1/groups/{target_id}").json()
        target_img_ids = [img["id"] for img in detail["images"]]
        total_expected = len(data["source_img_ids"]) + len(data["target_img_ids"])
        assert len(target_img_ids) == total_expected

    def test_self_merge_returns_400(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.post(
            f"/api/v1/groups/{group_id}/merge",
            json={"target_group_id": group_id},
        )
        assert resp.status_code == 400

    def test_merge_nonexistent_source_returns_404(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.post(
            "/api/v1/groups/999999/merge",
            json={"target_group_id": group_id},
        )
        assert resp.status_code == 404

    def test_merge_nonexistent_target_returns_404(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.post(
            f"/api/v1/groups/{group_id}/merge",
            json={"target_group_id": 999999},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/groups/{id}
# ---------------------------------------------------------------------------


class TestGroupEditAdvanced:
    """Cover lines missed by TestGroupEdit: image_type update, primary reassignment, split."""

    def test_update_image_type_persists(self, seeded_group):
        """Setting image_type on a kept image (line 173) should be saved."""
        client, group_id, img_ids = seeded_group
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_ids[0],
                        "name": "img0",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": "scene",
                        "tags": [],
                    },
                    *[
                        {
                            "id": img_id,
                            "name": f"img{i + 1}",
                            "gridded": None,
                            "grid_width": None,
                            "grid_height": None,
                            "subgroup": None,
                            "image_type": None,
                            "tags": [],
                        }
                        for i, img_id in enumerate(img_ids[1:])
                    ],
                ],
                "new_groups": [],
            },
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/v1/groups/{group_id}").json()
        img0 = next(img for img in detail["images"] if img["id"] == img_ids[0])
        assert img0["image_type"] == "scene"

    def test_delete_primary_image_reassigns_primary(self, seeded_group):
        """When the primary image is deleted (lines 191-192), primary_image_id is updated."""
        client, group_id, img_ids = seeded_group
        # img_ids[0] is the primary; delete it by keeping only [1] and [2]
        kept = img_ids[1:]
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_id,
                        "name": f"img{i}",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    }
                    for i, img_id in enumerate(kept)
                ],
                "new_groups": [],
            },
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/v1/groups/{group_id}").json()
        # primary_image_id must now point at one of the remaining images
        assert detail["primary_image_id"] in kept

    def test_split_off_new_group(self, seeded_group):
        """Create a split-off group from a subset of images.

        Images referenced in new_groups are moved, not deleted — they don't
        need to appear in payload.images (but may, for metadata updates).
        """
        client, group_id, img_ids = seeded_group
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_ids[0],
                        "name": "Ancient Ruins Day",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    },
                    {
                        "id": img_ids[1],
                        "name": "Ancient Ruins Night",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    },
                    {
                        "id": img_ids[2],
                        "name": "Ancient Ruins Winter",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    },
                ],
                "new_groups": [
                    {
                        "base_name": "Ancient Ruins Night Edition",
                        "author": "TestAuthor",
                        "image_ids": [img_ids[1]],
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["new_group_ids"]) == 1
        new_group_id = data["new_group_ids"][0]

        # New group should exist with the split image
        new_group = client.get(f"/api/v1/groups/{new_group_id}").json()
        assert new_group["base_name"] == "Ancient Ruins Night Edition"
        assert any(img["id"] == img_ids[1] for img in new_group["images"])

    def test_split_does_not_delete_moved_images(self, seeded_group):
        """Images in new_groups but NOT in payload.images must be moved, not deleted.

        Regression test: previously, omitting moved images from payload.images
        caused them to be permanently deleted before the new group assignment.
        """
        client, group_id, img_ids = seeded_group
        # Only include img_ids[0] in images — split img_ids[1] without listing it
        resp = client.put(
            f"/api/v1/groups/{group_id}",
            json={
                "base_name": "Ancient Ruins",
                "author": "TestAuthor",
                "images": [
                    {
                        "id": img_ids[0],
                        "name": "Ancient Ruins Day",
                        "gridded": None,
                        "grid_width": None,
                        "grid_height": None,
                        "subgroup": None,
                        "image_type": None,
                        "tags": [],
                    },
                ],
                "new_groups": [
                    {
                        "base_name": "Split Group",
                        "author": "TestAuthor",
                        "image_ids": [img_ids[1]],
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # img_ids[2] was in neither images nor new_groups — it should be deleted
        assert img_ids[2] in data["deleted_image_ids"]
        # img_ids[1] was in new_groups — it must NOT be deleted
        assert img_ids[1] not in data["deleted_image_ids"]

        # The new group should contain the moved image
        new_group_id = data["new_group_ids"][0]
        new_group = client.get(f"/api/v1/groups/{new_group_id}").json()
        assert any(img["id"] == img_ids[1] for img in new_group["images"])

        # The source group should only have img_ids[0]
        source = client.get(f"/api/v1/groups/{group_id}").json()
        source_img_ids = [img["id"] for img in source["images"]]
        assert img_ids[0] in source_img_ids
        assert img_ids[1] not in source_img_ids


class TestGroupDelete:
    def test_delete_removes_group_and_images(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.delete(f"/api/v1/groups/{group_id}")
        assert resp.status_code == 200

        # Group gone
        assert client.get(f"/api/v1/groups/{group_id}").status_code == 404

    def test_delete_nonexistent_group_returns_404(self, seeded_group):
        client, _, _ = seeded_group
        resp = client.delete("/api/v1/groups/999999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/groups/{id}/move-images
# ---------------------------------------------------------------------------


class TestGroupMoveImages:
    def test_move_subset_of_images(self, two_groups):
        """Move one image from source to target; source keeps the other."""
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]
        moved_img = data["source_img_ids"][0]

        resp = client.post(
            f"/api/v1/groups/{source_id}/move-images",
            json={"target_group_id": target_id, "image_ids": [moved_img]},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["images_moved"] == 1
        assert result["source_group_deleted"] is False

        # Image now in target
        target_detail = client.get(f"/api/v1/groups/{target_id}").json()
        target_img_ids = [img["id"] for img in target_detail["images"]]
        assert moved_img in target_img_ids

        # Source still exists with remaining image
        source_detail = client.get(f"/api/v1/groups/{source_id}").json()
        assert len(source_detail["images"]) == 1
        assert source_detail["images"][0]["id"] == data["source_img_ids"][1]

    def test_move_all_images_deletes_source(self, two_groups):
        """Moving all images from source auto-deletes the empty source group."""
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]

        resp = client.post(
            f"/api/v1/groups/{source_id}/move-images",
            json={"target_group_id": target_id, "image_ids": data["source_img_ids"]},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["images_moved"] == 2
        assert result["source_group_deleted"] is True

        # Source group no longer exists
        assert client.get(f"/api/v1/groups/{source_id}").status_code == 404

        # All images are now in target
        target_detail = client.get(f"/api/v1/groups/{target_id}").json()
        target_img_ids = {img["id"] for img in target_detail["images"]}
        for img_id in data["source_img_ids"]:
            assert img_id in target_img_ids

    def test_moved_images_inherit_target_author(self, two_groups):
        """Moved images should have their author synced to the target group."""
        client, data = two_groups
        target_id = data["target_id"]
        moved_img = data["source_img_ids"][0]

        client.post(
            f"/api/v1/groups/{data['source_id']}/move-images",
            json={"target_group_id": target_id, "image_ids": [moved_img]},
        )

        target_detail = client.get(f"/api/v1/groups/{target_id}").json()
        moved = next(img for img in target_detail["images"] if img["id"] == moved_img)
        assert moved["author"] == "AuthorB"  # target group's author

    def test_move_reassigns_primary_image_on_source(self, two_groups):
        """If the source's primary image is moved, primary_image_id is reassigned."""
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]
        # img_s1 is the primary (set in the fixture)
        primary_img = data["source_img_ids"][0]
        remaining_img = data["source_img_ids"][1]

        client.post(
            f"/api/v1/groups/{source_id}/move-images",
            json={"target_group_id": target_id, "image_ids": [primary_img]},
        )

        source_detail = client.get(f"/api/v1/groups/{source_id}").json()
        assert source_detail["primary_image_id"] == remaining_img

    def test_self_move_returns_400(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.post(
            f"/api/v1/groups/{group_id}/move-images",
            json={"target_group_id": group_id, "image_ids": [img_ids[0]]},
        )
        assert resp.status_code == 400

    def test_move_nonexistent_source_returns_404(self, seeded_group):
        client, group_id, _ = seeded_group
        resp = client.post(
            "/api/v1/groups/999999/move-images",
            json={"target_group_id": group_id, "image_ids": [1]},
        )
        assert resp.status_code == 404

    def test_move_nonexistent_target_returns_404(self, seeded_group):
        client, group_id, img_ids = seeded_group
        resp = client.post(
            f"/api/v1/groups/{group_id}/move-images",
            json={"target_group_id": 999999, "image_ids": [img_ids[0]]},
        )
        assert resp.status_code == 404

    def test_move_image_not_in_source_returns_400(self, two_groups):
        """Image IDs that don't belong to the source group should fail."""
        client, data = two_groups
        source_id = data["source_id"]
        target_id = data["target_id"]
        # target_img_ids[0] belongs to the target, not the source
        wrong_img = data["target_img_ids"][0]

        resp = client.post(
            f"/api/v1/groups/{source_id}/move-images",
            json={"target_group_id": target_id, "image_ids": [wrong_img]},
        )
        assert resp.status_code == 400


def test_concurrent_identical_moves_succeed_once(two_groups):
    """Write endpoints take the SQLite write lock up front, so the ownership check
    and the move can't interleave between concurrent requests."""
    from concurrent.futures import ThreadPoolExecutor

    client, data = two_groups
    body = {"target_group_id": data["target_id"], "image_ids": [data["source_img_ids"][0]]}
    url = f"/api/v1/groups/{data['source_id']}/move-images"
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: client.post(url, json=body).status_code, range(8)))
    assert codes.count(200) == 1, codes

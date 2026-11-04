"""The API refuses what an export would have to cut short or drop
(design/export-backup-move.md §2), so what's in the library always exports as it is."""

import pytest

from backend.app.models import Image, ImageGroup


@pytest.fixture
def ids(tmp_db):
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        group = ImageGroup(base_name="Forest")
        db.add(group)
        db.flush()
        image = Image(filename="a.png", storage_key="a.png", name="A", group_id=group.id)
        db.add(image)
        db.commit()
        return {"image": image.id, "group": group.id}


@pytest.mark.parametrize(
    "body",
    [
        {"grid_type": "Square"},
        {"grid_type": "triangle"},
        {"grid_width": 0},
        {"grid_height": 20_000},
        {"name": "x" * 501},
        {"subgroup": "x" * 501},
    ],
)
def test_image_patch_refuses(test_client, ids, body):
    assert test_client.patch(f"/api/v1/images/{ids['image']}", json=body).status_code == 422


def test_image_patch_takes_values_within_the_limits(test_client, ids):
    body = {"gridded": True, "grid_type": "hex", "grid_width": 30, "grid_height": 20}
    response = test_client.patch(f"/api/v1/images/{ids['image']}", json=body)
    assert response.status_code == 200
    assert response.json()["grid_type"] == "hex"


@pytest.mark.parametrize(
    "tag",
    [
        {"category": "", "value": "x"},
        {"category": "season", "value": ""},
        {"category": "season", "value": "x" * 101},
        {"category": "season", "value": "x", "confidence": 2},
    ],
)
def test_tags_refuse(test_client, ids, tag):
    assert test_client.post(f"/api/v1/tags/image/{ids['image']}", json=tag).status_code == 422
    bulk = {"image_ids": [ids["image"]], "add_tags": [tag]}
    assert test_client.post("/api/v1/images/bulk-edit", json=bulk).status_code == 422


def test_bulk_edit_refuses_a_bad_grid(test_client, ids):
    bulk = {"image_ids": [ids["image"]], "changes": {"grid_type": "SQUARE"}}
    assert test_client.post("/api/v1/images/bulk-edit", json=bulk).status_code == 422


def test_group_edit_refuses_long_names(test_client, ids):
    body = {"base_name": "x" * 501, "images": []}
    assert test_client.put(f"/api/v1/groups/{ids['group']}", json=body).status_code == 422
    body = {"ids": [ids["group"]], "author": "x" * 501}
    assert test_client.post("/api/v1/groups/bulk-update", json=body).status_code == 422


def test_tag_vocabulary_limits(test_client):
    assert test_client.post("/api/v1/tags/categories", json={"name": ""}).status_code == 422
    too_long = "x" * 101
    assert test_client.put(f"/api/v1/tags/categories/season/tags/{too_long}").status_code == 422
    aliases = ["a"] * 101
    response = test_client.put("/api/v1/tags/categories/season/tags/snowy", json=aliases)
    assert response.status_code == 422

"""Groups record user edits (ADR-028, design/variant-grouping.md §6).

Every user edit of a group's metadata or membership sets ``ImageGroup.edited_at``, so
automatic grouping (refinement) never changes it. Edits that don't touch a group's
structure (a tag, a grid) through the image endpoints leave it alone.
"""

from __future__ import annotations

import pytest

from backend.app.models.database import Image, ImageGroup

GROUPS = "/api/v1/groups"
IMAGES = "/api/v1/images"


@pytest.fixture
def library(test_client, tmp_db):
    """Two groups of two images each: (client, SessionLocal, {name: group id}, {name: ids})."""
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        groups, images = {}, {}
        for name in ("Forest Path", "Forest Cave"):
            group = ImageGroup(base_name=name, author="Czepeku")
            db.add(group)
            db.flush()
            groups[name] = group.id
            images[name] = []
            for variant in ("Day", "Night"):
                image = Image(
                    name=f"{name} {variant}",
                    filename=f"{name} {variant}.jpg".replace(" ", "_"),
                    author="Czepeku",
                    storage_key=f"{name}-{variant}.jpg".replace(" ", "_").lower(),
                    group_id=group.id,
                    media_type="image",
                    image_type="battlemap",
                )
                db.add(image)
                db.flush()
                images[name].append(image.id)
        db.commit()
    return test_client, SessionLocal, groups, images


def edited(SessionLocal) -> dict[int, bool]:
    with SessionLocal() as db:
        return {g.id: g.edited_at is not None for g in db.query(ImageGroup)}


def image_payload(image_id: int, **fields) -> dict:
    return {"id": image_id, "name": f"img{image_id}", "tags": [], **fields}


def test_nothing_is_edited_to_begin_with(library):
    _client, SessionLocal, groups, _ = library
    assert edited(SessionLocal) == dict.fromkeys(groups.values(), False)


def test_editing_a_group_marks_it(library):
    client, SessionLocal, groups, images = library
    path = groups["Forest Path"]
    body = {
        "base_name": "Forest Trail",
        "author": "Czepeku",
        "images": [image_payload(i) for i in images["Forest Path"]],
    }
    assert client.put(f"{GROUPS}/{path}", json=body).status_code == 200
    assert edited(SessionLocal) == {path: True, groups["Forest Cave"]: False}


def test_deleting_an_image_in_the_editor_marks_its_group(library):
    client, SessionLocal, groups, images = library
    path = groups["Forest Path"]
    keep, drop = images["Forest Path"]
    body = {
        "base_name": "Forest Path",
        "author": "Czepeku",
        "images": [image_payload(keep)],
        "delete_image_ids": [drop],
    }
    assert client.put(f"{GROUPS}/{path}", json=body).status_code == 200
    assert edited(SessionLocal)[path] is True


def test_a_split_marks_the_group_and_the_new_one(library):
    client, SessionLocal, groups, images = library
    path = groups["Forest Path"]
    day, night = images["Forest Path"]
    body = {
        "base_name": "Forest Path",
        "author": "Czepeku",
        "images": [image_payload(day)],
        "new_groups": [
            {"base_name": "Forest Path Night", "author": "Czepeku", "image_ids": [night]}
        ],
    }
    response = client.put(f"{GROUPS}/{path}", json=body).json()
    (new_id,) = response["new_group_ids"]
    assert edited(SessionLocal) == {path: True, groups["Forest Cave"]: False, new_id: True}


def test_moving_images_marks_both_groups(library):
    client, SessionLocal, groups, images = library
    path, cave = groups["Forest Path"], groups["Forest Cave"]
    body = {"target_group_id": cave, "image_ids": images["Forest Path"][:1]}
    assert client.post(f"{GROUPS}/{path}/move-images", json=body).status_code == 200
    assert edited(SessionLocal) == {path: True, cave: True}


def test_moving_images_into_a_new_group_marks_it(library):
    client, SessionLocal, groups, images = library
    path = groups["Forest Path"]
    body = {"new_group_name": "Forest Path Night", "image_ids": images["Forest Path"][1:]}
    response = client.post(f"{GROUPS}/{path}/move-images", json=body).json()
    assert edited(SessionLocal)[response["target_group_id"]] is True
    assert edited(SessionLocal)[path] is True


def test_merging_marks_the_survivor(library):
    client, SessionLocal, groups, _ = library
    path, cave = groups["Forest Path"], groups["Forest Cave"]
    assert client.post(f"{GROUPS}/{path}/merge", json={"target_group_id": cave}).status_code == 200
    assert edited(SessionLocal) == {cave: True}  # the source is gone


def test_setting_many_groups_author_marks_them(library):
    client, SessionLocal, groups, _ = library
    body = {"ids": [groups["Forest Path"]], "author": "Someone"}
    assert client.post(f"{GROUPS}/bulk-update", json=body).status_code == 200
    assert edited(SessionLocal) == {groups["Forest Path"]: True, groups["Forest Cave"]: False}


def test_a_subgroup_change_marks_the_group_and_other_image_edits_do_not(library):
    client, SessionLocal, groups, images = library
    day = images["Forest Path"][0]
    assert client.patch(f"{IMAGES}/{day}", json={"gridded": False}).status_code == 200
    assert not any(edited(SessionLocal).values())
    assert client.patch(f"{IMAGES}/{day}", json={"subgroup": None}).status_code == 200
    assert not any(edited(SessionLocal).values())  # unchanged
    assert client.patch(f"{IMAGES}/{day}", json={"subgroup": "Gridless"}).status_code == 200
    assert edited(SessionLocal) == {groups["Forest Path"]: True, groups["Forest Cave"]: False}


def test_bulk_subgroup_edits_and_their_undo_mark_the_groups(library):
    client, SessionLocal, groups, images = library
    tags_only = {
        "image_ids": images["Forest Cave"],
        "add_tags": [{"category": "time", "value": "night"}],
    }
    assert client.post(f"{IMAGES}/bulk-edit", json=tags_only).status_code == 200
    assert not any(edited(SessionLocal).values())

    body = {"image_ids": images["Forest Path"], "changes": {"subgroup": "Gridded"}}
    response = client.post(f"{IMAGES}/bulk-edit", json=body).json()
    assert edited(SessionLocal) == {groups["Forest Path"]: True, groups["Forest Cave"]: False}

    with SessionLocal() as db:
        db.query(ImageGroup).update({"edited_at": None})
        db.commit()
    restored = client.post(f"{IMAGES}/bulk-restore", json={"undo_id": response["undo_id"]})
    assert restored.status_code == 200
    assert edited(SessionLocal) == {groups["Forest Path"]: True, groups["Forest Cave"]: False}


def test_deleting_an_image_marks_its_group(library):
    client, SessionLocal, groups, images = library
    assert client.delete(f"{IMAGES}/{images['Forest Cave'][0]}").status_code == 200
    assert edited(SessionLocal) == {groups["Forest Path"]: False, groups["Forest Cave"]: True}

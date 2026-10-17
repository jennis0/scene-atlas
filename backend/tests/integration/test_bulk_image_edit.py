"""Integration tests for POST /api/v1/images/bulk-edit and /bulk-restore."""

import pytest

from backend.app.models.database import GRID_SOURCE_USER, Image, ImageGroup, Tag
from backend.app.services.fts_service import search_text_for

EDIT = "/api/v1/images/bulk-edit"
RESTORE = "/api/v1/images/bulk-restore"


@pytest.fixture
def seeded(test_client, tmp_db):
    """Three images in one group: one gridded by the detector, one tagged 'night'."""
    _, SessionLocal = tmp_db
    with SessionLocal() as db:
        group = ImageGroup(base_name="Ruins", author="A")
        db.add(group)
        db.flush()
        detected = Image(
            name="Ruins Day",
            filename="day.jpg",
            storage_key="day.jpg",
            group_id=group.id,
            image_type="battlemap",
            gridded=True,
            grid_type="square",
            grid_width=20,
            grid_height=15,
            grid_source="detector",
            grid_confidence=0.9,
        )
        tagged = Image(name="Ruins Night", filename="night.jpg", storage_key="night.jpg")
        plain = Image(name="Ruins Snow", filename="snow.jpg", storage_key="snow.jpg")
        for img in (tagged, plain):
            img.group_id = group.id
            img.image_type = "battlemap"
        db.add_all([detected, tagged, plain])
        db.flush()
        db.add(Tag(image_id=tagged.id, category="lighting", value="night"))
        db.flush()
        # As ingest leaves them, so an undo can be compared with the original exactly
        for img in (detected, tagged, plain):
            db.refresh(img)
            img.search_text = search_text_for(img)
        db.commit()
        ids = [detected.id, tagged.id, plain.id]
    return test_client, SessionLocal, ids


def _image(SessionLocal, image_id: int) -> dict:
    with SessionLocal() as db:
        img = db.get(Image, image_id)
        assert img is not None
        return {
            "image_type": img.image_type,
            "subgroup": img.subgroup,
            "gridded": img.gridded,
            "grid_type": img.grid_type,
            "grid_width": img.grid_width,
            "grid_height": img.grid_height,
            "grid_source": img.grid_source,
            "grid_confidence": img.grid_confidence,
            "tags": sorted((t.category, t.value) for t in img.tags),
            "search_text": img.search_text,
        }


class TestBulkEdit:
    def test_adds_a_tag_once_and_indexes_it(self, seeded):
        client, SessionLocal, ids = seeded
        resp = client.post(
            EDIT, json={"image_ids": ids, "add_tags": [{"category": "lighting", "value": "night"}]}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated"] == 3
        # The tagged image already had it
        assert len(body["added_tag_ids"]) == 2
        for image_id in ids:
            image = _image(SessionLocal, image_id)
            assert image["tags"] == [("lighting", "night")]
            assert "night" in (image["search_text"] or "").lower()

    def test_grid_change_takes_over_from_the_detector(self, seeded):
        client, SessionLocal, ids = seeded
        resp = client.post(EDIT, json={"image_ids": ids[:1], "changes": {"grid_type": "hex"}})
        assert resp.status_code == 200
        image = _image(SessionLocal, ids[0])
        assert image["grid_type"] == "hex"
        assert image["grid_source"] == GRID_SOURCE_USER
        assert image["grid_confidence"] is None
        assert image["grid_width"] == 20

    def test_turning_the_grid_off_clears_its_fields(self, seeded):
        client, SessionLocal, ids = seeded
        client.post(EDIT, json={"image_ids": ids[:1], "changes": {"gridded": False}})
        image = _image(SessionLocal, ids[0])
        assert image["gridded"] is False
        assert (image["grid_type"], image["grid_width"], image["grid_height"]) == (None,) * 3

    def test_sets_type_and_subgroup_leaving_other_fields(self, seeded):
        client, SessionLocal, ids = seeded
        changes = {"image_type": "scene", "subgroup": "Winter"}
        client.post(EDIT, json={"image_ids": ids, "changes": changes})
        for image_id in ids:
            image = _image(SessionLocal, image_id)
            assert image["image_type"] == "scene"
            assert image["subgroup"] == "Winter"
            assert "winter" in (image["search_text"] or "").lower()
        assert _image(SessionLocal, ids[0])["grid_source"] == "detector"

    def test_null_clears_a_field(self, seeded):
        client, SessionLocal, ids = seeded
        client.post(EDIT, json={"image_ids": ids, "changes": {"subgroup": "Winter"}})
        client.post(EDIT, json={"image_ids": ids, "changes": {"subgroup": None}})
        assert all(_image(SessionLocal, i)["subgroup"] is None for i in ids)

    def test_skips_unknown_ids(self, seeded):
        client, _, ids = seeded
        resp = client.post(EDIT, json={"image_ids": [*ids, 999_999], "changes": {}})
        assert resp.json()["updated"] == 3

    @pytest.mark.parametrize(
        "payload", [{"image_ids": []}, {"image_ids": [1], "changes": {"image_type": "map"}}]
    )
    def test_rejects_bad_requests(self, test_client, payload):
        assert test_client.post(EDIT, json=payload).status_code == 422


class TestBulkRestore:
    def test_undo_puts_everything_back(self, seeded):
        client, SessionLocal, ids = seeded
        before = [_image(SessionLocal, i) for i in ids]
        edit = client.post(
            EDIT,
            json={
                "image_ids": ids,
                "changes": {"gridded": False, "image_type": "scene", "subgroup": "Winter"},
                "add_tags": [{"category": "lighting", "value": "night"}],
            },
        ).json()
        assert [_image(SessionLocal, i) for i in ids] != before

        resp = client.post(
            RESTORE, json={"images": edit["previous"], "remove_tag_ids": edit["added_tag_ids"]}
        )
        assert resp.status_code == 200
        assert resp.json()["restored"] == 3
        assert [_image(SessionLocal, i) for i in ids] == before

    def test_only_removes_tags_of_restored_images(self, seeded):
        client, SessionLocal, ids = seeded
        with SessionLocal() as db:
            other_tag = db.query(Tag).filter(Tag.image_id == ids[1]).one().id
        edit = client.post(
            EDIT,
            json={"image_ids": ids[:1], "add_tags": [{"category": "season", "value": "winter"}]},
        ).json()
        client.post(
            RESTORE,
            json={
                "images": edit["previous"],
                "remove_tag_ids": [*edit["added_tag_ids"], other_tag],
            },
        )
        assert _image(SessionLocal, ids[0])["tags"] == []
        assert _image(SessionLocal, ids[1])["tags"] == [("lighting", "night")]
